"""Four disjoint full-S partitions, one VM, one shared billing ledger."""

import argparse
import json
import multiprocessing
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from scripts._benchmark_runtime import Ledger, atomic_json, digest
from scripts._experiment_contracts import EvaluationPlan
from scripts._experiment_store import exclusive_path
from scripts._longmemeval_harness import code_identity, report, validate_instances
from scripts.experiment_pipeline import execute_plan, ledger_snapshot, load
from scripts.experiment_pipeline import main as controller

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ".benchmark-artifacts"
BASE = ART / "parallel-full-s"
WORKERS = 4


def partition(rows):
    validate_instances(rows)
    ordered = sorted(rows, key=lambda row: row["question_id"])
    groups = [ordered[index::WORKERS] for index in range(WORKERS)]
    validate_partition(ordered, groups)
    return groups


def validate_partition(original, groups):
    expected = {row["question_id"]: digest(row) for row in original}
    actual = [(row["question_id"], digest(row)) for group in groups for row in group]
    if (
        len(actual) != len(expected)
        or len({key for key, _ in actual}) != len(actual)
        or dict(actual) != expected
    ):
        raise ValueError(
            "Partitions must preserve every original question exactly once"
        )


def prepare():
    from scripts.benchmark_cloud_runner import validate_tool_proof

    rows = load(ART / "data/longmemeval_s_cleaned.json")
    if len(rows) != 500:
        raise ValueError("Full S launch requires the frozen 500-question corpus")
    groups = partition(rows)
    profile = load(ART / "cloud-profile.json")
    validate_tool_proof(profile, ART)
    profile["ingestion_workers"] = 2
    profile_path = BASE / "profile.json"
    atomic_json(profile_path, profile)
    quotes, plans = [], []
    for index, group in enumerate(groups):
        directory = BASE / f"worker-{index}"
        data = directory / "data.json"
        atomic_json(data, group)
        result = controller(
            [
                "plan",
                "--data",
                str(data),
                "--profile",
                str(profile_path),
                "--mode",
                "compare",
                "--dataset-profile",
                "s_cleaned",
                "--split",
                "all",
                "--limit",
                str(len(group)),
                "--launch-strategy",
                "full_baseline",
                "--max-cost-usd",
                "20",
                "--max-calls",
                "300000",
                "--reserve-usd",
                "5",
                "--experiment-id",
                f"gcp-full-s-parallel-partition-{index}",
                "--output",
                str(directory / "plan"),
            ]
        )
        plans.append(result["plan_sha256"])
        quotes.append(result["cost"]["uncached_upper_bound_usd"])
        # Reuse only exact existing embedding HTTP requests. The cache identity
        # contains the model/preprocessing conventions; corpus scopes stay local.
        for row in group:
            old_key = digest([digest(rows), row["question_id"], profile["embedding"]])
            new_key = digest([digest(group), row["question_id"], profile["embedding"]])
            old = ART / "cache/embedding-instances" / old_key
            new = ART / "cache/embedding-instances" / new_key
            if old.exists():
                shutil.copytree(old, new, dirs_exist_ok=True)
    from decimal import Decimal

    upper = sum(Decimal(value) for value in quotes)
    prior = Decimal(ledger_snapshot(ART)["spent_or_reserved_usd"])
    if upper + prior > Decimal("20"):
        raise ValueError("Combined partition quote does not fit shared USD20 cap")
    manifest = {
        "schema_version": 1,
        "experiment_id": "gcp-full-s-parallel",
        "original_dataset_sha256": digest(rows),
        "question_ids": sorted(row["question_id"] for row in rows),
        "partitions": [[row["question_id"] for row in group] for group in groups],
        "plan_sha256": plans,
        "code": code_identity(),
        "profile_sha256": digest(profile),
        "modes": ["direct", "hermes"],
        "workers": WORKERS,
        "embedding_workers_per_question": 2,
        "shared_billing_root": str(ART),
        "cumulative_cap_usd": "20",
        "combined_upper_bound_usd": str(upper),
        "prior_spent_or_reserved_usd": str(prior),
        "scope": "Pinned Hermes backend with shared authorized per-question index; not full AgentService",
        "note": "Execution partitions of the same original full S corpus; all IDs retained. Earlier diagnostic attempts remain separate.",
    }
    atomic_json(BASE / "manifest.json", manifest)
    return manifest


def execute_partition(index):
    directory = BASE / f"worker-{index}"
    path = directory / "plan/plan.json"
    plan = EvaluationPlan.model_validate(load(path))
    try:
        result = execute_plan(
            plan,
            SimpleNamespace(
                live=True,
                replay=False,
                plan=str(path),
                approval=str(directory / "plan/approval.json"),
                run_dir=str(directory / "run"),
                artifact_root=str(ART),
            ),
        )
        return {
            "partition": index,
            "state": "returned",
            "valid_grades": result["valid_grades"],
        }
    except BaseException as error:
        atomic_json(directory / "error.json", {"error_class": type(error).__name__})
        return {
            "partition": index,
            "state": "failed",
            "error_class": type(error).__name__,
        }


def collect(manifest):
    records = []
    workers = []
    for index, ids in enumerate(manifest["partitions"]):
        path = BASE / f"worker-{index}/run/report.json"
        rows = load(path)["questions_detail"] if path.exists() else []
        if any(
            row["question_id"] not in ids or row["mode"] not in manifest["modes"]
            for row in rows
        ):
            raise ValueError("Worker report crosses its frozen partition")
        records.extend(rows)
        workers.append(
            {
                "partition": index,
                "recorded": len(rows),
                "graded": sum(row["status"] == "graded" for row in rows),
            }
        )
    keys = [(row["question_id"], row["mode"]) for row in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate question/mode outcomes across partitions")
    return records, workers


def run():
    if not os.environ.get("NEBIUS_API_KEY"):
        raise ValueError("Supply private API key in the service environment")
    manifest = load(BASE / "manifest.json")
    if manifest["code"] != code_identity():
        raise ValueError("Code changed after partition planning")
    ledger = Ledger(ART / "budget.sqlite3", "20", 300000)
    baseline = ledger.summary()["calls"]
    started = time.monotonic()
    with (
        exclusive_path(BASE / "owner.lock"),
        ProcessPoolExecutor(
            max_workers=WORKERS, mp_context=multiprocessing.get_context("spawn")
        ) as pool,
    ):
        futures = [pool.submit(execute_partition, index) for index in range(WORKERS)]
        while True:
            records, workers = collect(manifest)
            combined = report(records, manifest, 1000, ledger)
            done = all(future.done() for future in futures)
            state = "running"
            if done:
                state = (
                    "finished"
                    if combined["valid_grades"] == 1000
                    else "stopped_incomplete"
                )
            live = {
                "state": state,
                "elapsed_seconds": round(time.monotonic() - started),
                "planned": 1000,
                "completed_answers": combined["completed_answers"],
                "valid_grades": combined["valid_grades"],
                "correct": combined["correct"],
                "status_counts": combined["status_counts"],
                "workers": workers,
                "new_requests": ledger.summary()["calls"] - baseline,
                "ledger": ledger.summary(),
                "question_workers": WORKERS,
                "embedding_workers_per_question": 2,
                "updated_utc": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
            }
            atomic_json(BASE / "report.json", combined)
            atomic_json(BASE / "live-status.json", live)
            print(json.dumps(live), flush=True)
            if done:
                atomic_json(
                    BASE / "worker-outcomes.json",
                    [future.result() for future in futures],
                )
                break
            time.sleep(20)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "run"])
    options = parser.parse_args()
    os.chdir(ROOT)
    if options.operation == "prepare":
        print(json.dumps(prepare(), indent=2))
    else:
        run()


if __name__ == "__main__":
    main()
