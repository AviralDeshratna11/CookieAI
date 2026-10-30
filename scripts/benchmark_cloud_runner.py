"""Approved full benchmark runner with credential-free live progress snapshots."""

import argparse
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts._benchmark_runtime import atomic_json, digest
from scripts._experiment_contracts import EvaluationPlan
from scripts._experiment_store import exclusive_path
from scripts.experiment_pipeline import execute_plan, ledger_snapshot, load
from scripts.experiment_pipeline import main as controller

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".benchmark-artifacts"
PLAN = ARTIFACTS / "cloud-full-s-plan-v2"
RUN = ARTIFACTS / "cloud-full-s-run-v2"


def progress(state, started, baseline):
    report = load(RUN / "report.json") if (RUN / "report.json").exists() else {}
    ledger = ledger_snapshot(ARTIFACTS)
    value = {
        **state,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started),
        "planned": 1000,
        "completed_answers": report.get("completed_answers", 0),
        "valid_grades": report.get("valid_grades", 0),
        "correct": report.get("correct", 0),
        "status_counts": report.get("status_counts", {}),
        "new_requests": ledger["calls"] - baseline,
        "ledger": ledger,
        "ingestion_workers": 4,
    }
    atomic_json(RUN / "live-status.json", value)
    print(__import__("json").dumps(value), flush=True)
    return value


def validate_tool_proof(profile, artifact_root):
    proof = Path(artifact_root) / "cache" / (digest(profile["answer"]) + ".tools.json")
    if not proof.exists() or load(proof).get("verified") is not True:
        raise ValueError(
            "Transfer the existing exact-route tool-probe proof before cloud preparation; no new probe is authorized implicitly"
        )
    return proof


def prepare():
    profile = load(ROOT / "config/benchmark.nebius.full-s.json")
    validate_tool_proof(profile, ARTIFACTS)
    profile["hermes"]["python"] = ".hermes-runtime/venv/bin/python"
    profile["ingestion_workers"] = 4
    path = ARTIFACTS / "cloud-profile.json"
    atomic_json(path, profile)
    return controller(
        [
            "plan",
            "--data",
            str(ARTIFACTS / "data/longmemeval_s_cleaned.json"),
            "--profile",
            str(path),
            "--mode",
            "compare",
            "--dataset-profile",
            "s_cleaned",
            "--split",
            "all",
            "--limit",
            "500",
            "--launch-strategy",
            "full_baseline",
            "--max-cost-usd",
            "20",
            "--max-calls",
            "300000",
            "--reserve-usd",
            "5",
            "--experiment-id",
            "gcp-full-s-500-shared-index-v2",
            "--output",
            str(PLAN),
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "run", "status"])
    options = parser.parse_args()
    os.chdir(ROOT)
    if options.operation == "prepare":
        prepare()
        return
    if options.operation == "status":
        print((RUN / "live-status.json").read_text())
        return
    if not os.environ.get("NEBIUS_API_KEY"):
        raise ValueError("Supply NEBIUS_API_KEY privately before starting")
    validate_tool_proof(load(ARTIFACTS / "cloud-profile.json"), ARTIFACTS)
    RUN.mkdir(parents=True, exist_ok=True)
    state = {"state": "starting", "pid": os.getpid()}
    started = time.monotonic()
    baseline = ledger_snapshot(ARTIFACTS)["calls"]
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            try:
                progress(state, started, baseline)
            except (OSError, ValueError):
                pass
            stop.wait(20)

    with exclusive_path(RUN / "launcher.lock"):
        worker = threading.Thread(target=monitor, daemon=True)
        worker.start()
        try:
            state["state"] = "running"
            plan = EvaluationPlan.model_validate(load(PLAN / "plan.json"))
            result = execute_plan(
                plan,
                SimpleNamespace(
                    live=True,
                    replay=False,
                    plan=str(PLAN / "plan.json"),
                    approval=str(PLAN / "approval.json"),
                    run_dir=str(RUN),
                    artifact_root=str(ARTIFACTS),
                ),
            )
            state["state"] = (
                "finished"
                if result.get("valid_grades") == 1000
                else "stopped_incomplete"
            )
        except BaseException as error:
            state.update(state="failed", error_class=type(error).__name__)
            atomic_json(
                RUN / "runner-error.json",
                {
                    "error_class": type(error).__name__,
                    "detail": str(error)
                    if isinstance(error, ValueError)
                    else "Exception body suppressed; inspect report",
                },
            )
            raise SystemExit(1) from None
        finally:
            stop.set()
            worker.join(timeout=5)
            progress(state, started, baseline)


if __name__ == "__main__":
    main()
