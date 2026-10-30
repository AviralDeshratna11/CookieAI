"""Offline-first experiment controller. No operation implicitly starts training."""

import argparse
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from scripts._benchmark_runtime import Ledger, atomic_json, digest, money_units, usd
from scripts._experiment_contracts import Approval, CostPlan, EvaluationPlan
from scripts._longmemeval_harness import (
    code_identity,
    select_instances,
    source_rows,
    validate_config,
    validate_instances,
)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ledger_snapshot(root):
    path = Path(root) / "budget.sqlite3"
    if not path.exists():
        return {"calls": 0, "spent_or_reserved_usd": "0"}
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        cost, calls = db.execute(
            "SELECT COALESCE(SUM(charged),0),COUNT(*) FROM requests"
        ).fetchone()
        cap, call_cap = db.execute("SELECT cap,calls FROM policy WHERE id=1").fetchone()
        return {
            "calls": calls,
            "spent_or_reserved_usd": usd(cost),
            "cap_usd": usd(cap),
            "call_cap": call_cap,
        }
    finally:
        db.close()


def estimate(selected, profile, modes):
    from memory.context.budget import TokenCounter
    from memory.entities.store import names
    from scripts._benchmark_runtime import validate_route
    from scripts._longmemeval_harness import ingestion_text

    counter = TokenCounter()
    texts = set()
    per_instance = []
    query_tokens = 0
    for row in selected:
        local = set()
        for source in source_rows(row):
            text = ingestion_text(source)
            local.add(" ".join(text.split()))
            local.update(names(SimpleNamespace(text=text, entities=[])))
        texts.update(local)
        per_instance.append(local)
        query_tokens += (counter.count(row["question"]) + 1024) * 4
    extra_query_calls = len(selected) * sum(
        8 if mode in {"hermes", "application"} else 0 for mode in modes
    )
    extra_application_vectors = len(selected) * sum(
        101 if mode == "application" else 0 for mode in modes
    )
    embedding = profile.get("embedding", {})
    batch = embedding.get("batch_size", 1)
    vectors = len(texts)
    document_tokens = sum(counter.count(t) for t in texts)
    if profile.get("storage_policy") == "rolling":
        vectors = sum(len(group) for group in per_instance)
        document_tokens = sum(
            counter.count(text) for group in per_instance for text in group
        )
    vectors += extra_application_vectors
    document_batches = (
        sum((len(group) + batch - 1) // batch for group in per_instance)
        if profile.get("storage_policy") == "rolling"
        else (vectors + batch - 1) // batch
    )
    bounds = {
        "embedding": {
            "input_tokens": document_tokens
            + query_tokens
            + extra_query_calls * (4000 + 1024)
            + extra_application_vectors * (4000 + 1024)
            + (document_batches + len(selected) * 4 + 1) * 1024,
            "output_tokens": 0,
            "calls": document_batches + len(selected) * 4 + extra_query_calls,
        },
        "answer": {
            "input_tokens": sum(
                3 if mode in {"hermes", "application"} else 1 for mode in modes
            )
            * len(selected)
            * profile.get("context_tokens", 32768),
            "output_tokens": sum(
                3 if mode in {"hermes", "application"} else 1 for mode in modes
            )
            * len(selected)
            * profile.get("output_tokens", 512),
            "calls": sum(
                3 if mode in {"hermes", "application"} else 1 for mode in modes
            )
            * len(selected),
        },
        "judge": {
            "input_tokens": len(selected)
            * len(modes)
            * profile.get("judge", {}).get("context_tokens", 32768),
            "output_tokens": len(selected)
            * len(modes)
            * profile.get("judge_output_tokens", 64),
            "calls": len(selected) * len(modes),
        },
    }
    if modes == ["retrieval-only"]:
        bounds.pop("answer")
        bounds.pop("judge")
    if embedding.get("backend", "hash-test") == "hash-test":
        bounds.pop("embedding")
    costs, blockers = {}, []
    for stage, tokens in bounds.items():
        route = (
            embedding.get("route", {})
            if stage == "embedding"
            else profile.get(stage, {})
        )
        try:
            validate_route(route, embedding=stage == "embedding")
            retries = route.get("attempts", 1)
            price = route["pricing"]
            total = (
                (
                    Decimal(str(price["input"])) * tokens["input_tokens"]
                    + Decimal(str(price["output"])) * tokens["output_tokens"]
                )
                * retries
                / 1_000_000
            )
            costs[stage] = str(total)
        except (ValueError, KeyError, TypeError) as error:
            blockers.append(f"{stage}: {error}")
    calibrated = {}
    from scripts._longmemeval_harness import ROOT

    historic = ROOT / "docs/benchmark-live-oracle-results.json"
    if historic.exists():
        previous = load(historic)
        for stage in ("answer", "judge"):
            if stage not in bounds or previous.get("manifest", {}).get(
                "config", {}
            ).get(stage, {}).get("model") != profile.get(stage, {}).get("model"):
                continue
            events = [
                event
                for row in previous.get("questions_detail", [])
                for event in row.get("events", [])
                if event["stage"] == stage
                and not event.get("cache_hit")
                and "usage" in event
            ]
            if events:
                price = profile[stage].get("pricing", {})
                if price.get("input") is not None and price.get("output") is not None:
                    sample_cost = (
                        sum(
                            Decimal(str(price["input"]))
                            * event["usage"]["prompt_tokens"]
                            + Decimal(str(price["output"]))
                            * event["usage"]["completion_tokens"]
                            for event in events
                        )
                        / len(events)
                        / 1_000_000
                    )
                    calibrated[stage] = {
                        "projected_usd": str(sample_cost * bounds[stage]["calls"]),
                        "observations": len(events),
                        "method": "Historical pilot mean tokens times current maximum call count; does not validate new tools or model quality",
                    }
    return {
        "uncached_upper_bound_usd": str(sum(Decimal(v) for v in costs.values()))
        if not blockers
        else None,
        "stage_costs": costs,
        "stages": bounds,
        "distinct_document_entity_vectors": vectors,
        "storage": {
            "policy": profile.get("storage_policy", "retain"),
            "peak_instance_vectors": max(map(len, per_instance), default=0),
            "conservative_projection_disk_bytes": (
                max(map(len, per_instance), default=0)
                if profile.get("storage_policy") == "rolling"
                else vectors
            )
            * 524288
            + 1073741824,
            "note": "Scratch/cache planning allowance; check free disk again before launch. Rolling evicts per-instance embedding cache and index after terminal outcomes.",
        },
        "price_blockers": blockers,
        "expected_usd": None,
        "historical_scenarios": calibrated,
        "assumptions": [
            "Measured source and entity strings; four query rewrites at most",
            "Answer/judge bounds use full declared request ceilings, not expected actual prompt sizes",
            "No fresh inference, no remote discovery, no assumption that cached responses are fresh trials",
            "Includes two new memory searches per Hermes/application execution; application turn/entity allowance is conservative",
            "Optional initial tool probes and repairs are excluded and must be separately planned; no repair is enabled",
        ],
    }


def plan_evaluation(options):
    from scripts._training_pipeline import EXPOSED

    rows = load(options.data)
    validate_instances(rows)
    config = load(options.profile) if options.profile else {}
    validate_config(config)
    selected, _ = select_instances(
        rows, options.limit, options.seed, 0.2, options.split
    )
    modes = ["direct", "hermes"] if options.mode == "compare" else [options.mode]
    quote = estimate(selected, config, modes)
    spend = ledger_snapshot(options.artifact_root)
    plan = EvaluationPlan(
        experiment_id=options.experiment_id,
        dataset_path=str(Path(options.data).resolve()),
        dataset_sha256=digest(rows),
        profile_path=str(Path(options.profile).resolve()) if options.profile else None,
        profile_sha256=digest(config),
        code_sha256=code_identity()["source_tree_sha256"],
        question_ids=[r["question_id"] for r in selected],
        modes=modes,
        split=options.split,
        seed=options.seed,
        dataset_profile=options.dataset_profile,
        top_k=options.top_k,
        neighbors=options.neighbors,
        development_exposed_ids=[
            r["question_id"] for r in selected if r["question_id"] in EXPOSED
        ],
        validation_report_path=str(Path(options.validation_report).resolve())
        if getattr(options, "validation_report", None)
        else None,
        validation_report_sha256=digest(load(options.validation_report))
        if getattr(options, "validation_report", None)
        else None,
        launch_strategy=getattr(options, "launch_strategy", "validated"),
        cost=CostPlan(
            cumulative_cap_usd=options.max_cost_usd,
            max_calls=options.max_calls,
            previous_spent_or_reserved_usd=spend["spent_or_reserved_usd"],
            reserve_usd=options.reserve_usd,
            upper_bound_usd=quote["uncached_upper_bound_usd"],
            assumptions=quote["assumptions"],
        ),
    )
    root = Path(options.output)
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / "plan.json", plan.model_dump(mode="json"))
    atomic_json(root / "cost-plan.json", quote)
    atomic_json(
        root / "approval.template.json",
        {
            "schema_version": 1,
            "action": "evaluation",
            "plan_sha256": plan.fingerprint,
            "approved_by": "",
            "approved_at": "",
            "expires_at": "",
            "approval_reference": "",
        },
    )
    return {
        "plan_sha256": plan.fingerprint,
        "questions": len(selected),
        "mode_count": len(modes),
        "cost": quote,
        "previous_ledger": spend,
        "network_calls": 0,
    }


def validate_plan(plan):
    rows = load(plan.dataset_path)
    validate_instances(rows)
    profile = load(plan.profile_path) if plan.profile_path else {}
    validate_config(profile)
    if (
        digest(rows) != plan.dataset_sha256
        or digest(profile) != plan.profile_sha256
        or code_identity()["source_tree_sha256"] != plan.code_sha256
    ):
        raise ValueError(
            "Frozen plan inputs/code changed; create and review a new plan"
        )
    selected, _ = select_instances(
        rows, len(plan.question_ids), plan.seed, plan.heldout_fraction, plan.split
    )
    if [r["question_id"] for r in selected] != plan.question_ids:
        raise ValueError("Frozen selection differs from planned IDs")
    return rows, profile


def validate_bound_plan(options, instances, config, selected):
    plan = EvaluationPlan.model_validate(load(options.approved_plan))
    approval = Approval.model_validate(load(options.approval))
    validate_plan(plan)
    approval.require("evaluation", plan.fingerprint)
    if len(plan.question_ids) > 12:
        validate_protocol_gate(plan)
    modes = ["direct", "hermes"] if options.mode == "compare" else [options.mode]
    if (
        plan.question_ids != [row["question_id"] for row in selected]
        or plan.modes != modes
        or digest(instances) != plan.dataset_sha256
        or digest(config) != plan.profile_sha256
        or options.top_k != plan.top_k
        or options.neighbors != plan.neighbors
        or options.dataset_profile != plan.dataset_profile
        or options.split != plan.split
        or str(options.max_cost_usd) != plan.cost.cumulative_cap_usd
        or options.max_calls != plan.cost.max_calls
    ):
        raise ValueError("Requested run is outside approved plan bounds")
    return plan


def remaining_cost_bound(plan, run_dir):
    """Price only uncompleted stages; never release earlier ledger reservations."""
    report_path = Path(run_dir) / "report.json"
    if not report_path.exists():
        return plan.cost.upper_bound_usd
    report = load(report_path)
    if report.get("manifest", {}).get("evaluation_plan_sha256") != plan.fingerprint:
        raise ValueError("Resume report belongs to a different frozen plan")
    indexed = {
        (row["question_id"], row["mode"]): row for row in report["questions_detail"]
    }
    if len(indexed) != len(report["questions_detail"]):
        raise ValueError("Resume report contains duplicate records")
    allowed = {(qid, mode) for qid in plan.question_ids for mode in plan.modes}
    if not set(indexed).issubset(allowed):
        raise ValueError("Resume report contains unplanned records")
    profile = load(plan.profile_path) if plan.profile_path else {}
    rows = {row["question_id"]: row for row in load(plan.dataset_path)}
    total = Decimal(0)
    ingestion = []
    for qid in plan.question_ids:
        needs_index = False
        for mode in plan.modes:
            record = indexed.get((qid, mode), {})
            if record.get("status") in {
                "graded",
                "retrieved",
                "invalid_final",
                "invalid_grade",
            }:
                continue
            quote = estimate([rows[qid]], profile, [mode])
            if quote["price_blockers"]:
                raise ValueError("Resume prices are not verified")
            if "prediction" not in record:
                needs_index = True
                total += Decimal(quote["stage_costs"].get("answer", "0"))
            total += Decimal(quote["stage_costs"].get("judge", "0"))
        if needs_index:
            ingestion.append(rows[qid])
    if ingestion:
        quote = estimate(ingestion, profile, plan.modes)
        total += Decimal(quote["stage_costs"].get("embedding", "0"))
    return str(total)


def execute_plan(plan, options):
    from scripts._longmemeval_harness import execute

    validate_plan(plan)
    if options.live:
        if not options.approval:
            raise ValueError("Live execution requires action-specific approval")
        approval = Approval.model_validate(load(options.approval))
        approval.require("evaluation", plan.fingerprint)
        if len(plan.question_ids) > 12:
            validate_protocol_gate(plan)
        if plan.cost.upper_bound_usd is None:
            raise ValueError("Resolve pricing blockers first")
        import shutil

        selected = [
            row
            for row in load(plan.dataset_path)
            if row["question_id"] in set(plan.question_ids)
        ]
        storage = estimate(
            selected, load(plan.profile_path) if plan.profile_path else {}, plan.modes
        )["storage"]
        if (
            shutil.disk_usage(Path(options.artifact_root).resolve()).free
            < storage["conservative_projection_disk_bytes"]
        ):
            raise ValueError("Insufficient free disk for planned scratch projections")
        remaining = remaining_cost_bound(plan, options.run_dir)
        if money_units(remaining) + money_units(
            ledger_snapshot(options.artifact_root)["spent_or_reserved_usd"]
        ) > money_units(plan.cost.cumulative_cap_usd):
            raise ValueError(
                "Conservative quote does not fit approved cumulative allocation"
            )
    modes = plan.modes
    if modes == ["direct", "hermes"]:
        mode = "compare"
    elif len(modes) == 1:
        mode = modes[0]
    else:
        raise ValueError("Unsupported mode grouping")
    args = SimpleNamespace(
        data=plan.dataset_path,
        profile=plan.profile_path,
        mode=mode,
        live=options.live,
        replay=options.replay,
        dry_run=False,
        limit=len(plan.question_ids),
        seed=plan.seed,
        heldout_fraction=plan.heldout_fraction,
        split=plan.split,
        dataset_profile=plan.dataset_profile,
        top_k=plan.top_k,
        neighbors=plan.neighbors,
        max_cost_usd=plan.cost.cumulative_cap_usd,
        max_calls=plan.cost.max_calls,
        artifact_root=options.artifact_root,
        run_dir=options.run_dir,
        probe_tools=False,
        approved_plan=options.plan,
        approval=options.approval,
    )
    return execute(args)


def validate_protocol_gate(plan):
    if plan.launch_strategy == "full_baseline":
        # Explicit operator-selected strategy, frozen in the approved plan.
        # This authorizes measurement without asserting validation or quality.
        return
    if not plan.validation_report_path or not plan.validation_report_sha256:
        raise ValueError(
            "Full paid run requires a frozen held-out protocol validation report"
        )
    report = load(plan.validation_report_path)
    if digest(report) != plan.validation_report_sha256:
        raise ValueError("Held-out protocol report changed")
    manifest = report["manifest"]
    if (
        manifest.get("split") != "heldout"
        or manifest.get("execution") != "live"
        or manifest.get("dataset_profile") != plan.dataset_profile
        or manifest.get("dataset_sha256") != plan.dataset_sha256
        or manifest.get("code", {}).get("source_tree_sha256") != plan.code_sha256
        or digest(manifest.get("config", {})) != plan.profile_sha256
        or manifest.get("modes") != plan.modes
    ):
        raise ValueError("Held-out validation provenance differs from planned full run")
    records = report["questions_detail"]
    from scripts._training_pipeline import EXPOSED

    dataset = load(plan.dataset_path)
    heldout, _ = select_instances(
        dataset, len(dataset), plan.seed, plan.heldout_fraction, "heldout"
    )
    permitted = {row["question_id"] for row in heldout} - set(EXPOSED)
    if not {row["question_id"] for row in records}.issubset(permitted):
        raise ValueError(
            "Protocol report includes development-exposed or non-heldout questions"
        )
    if not {row["question_id"] for row in records}.issubset(set(plan.question_ids)):
        raise ValueError("Protocol questions are outside the planned corpus selection")
    questions = len({row["question_id"] for row in records})
    invalid = sum(row["status"] == "invalid_final" for row in records)
    if (
        questions < plan.quality_gate["minimum_pilot_questions"]
        or not records
        or (report.get("completion_rate") or 0)
        < plan.quality_gate["minimum_completion_rate"]
        or invalid / len(records) > plan.quality_gate["maximum_invalid_final_rate"]
    ):
        raise ValueError("Held-out completion/format protocol gate failed")


def readiness():
    return {
        "offline_architecture": "implemented; see verification artifact for tested scope",
        "evaluation_paid_validation": "awaiting frozen plan and explicit approval",
        "full_evaluation": "full_baseline launch supported without a pilot; requires valid inputs and explicit budget approval; live quality unverified",
        "training_artifacts": "offline authored data pipeline available",
        "training_submission": "training_blocked: unsupported_model_or_account",
        "checkpoint_promotion": "blocked_no_trained_checkpoint",
        "paid_calls_started": False,
    }


def audit_recorded_failures(artifact_root):
    from scripts._benchmark_tools import date_interval
    from scripts._longmemeval_harness import ROOT
    from scripts._response_adapter import classify

    path = ROOT / "docs/benchmark-live-oracle-results.json"
    if not path.exists():
        return {"status": "blocked_missing_recorded_report", "network_calls": 0}
    report = load(path)
    findings = []
    for row in report["questions_detail"]:
        findings.append(
            {
                "question_id": row["question_id"],
                "mode": row["mode"],
                "original_status": row["status"],
                "original_correct": row.get("correct"),
                "session_recall": row.get("session_recall"),
                "missing_sessions": row.get("diagnostics", {}).get(
                    "missing_evidence_sessions", []
                ),
                "packing_omissions": len(
                    row.get("packing", {}).get("omitted_source_ids", [])
                ),
                "upstream_loss_stage": "not distinguishable from old trace; new per-candidate trace is required",
            }
        )
        for event in row.get("events", []):
            raw = Path(artifact_root) / "cache" / (event["fingerprint"] + ".json")
            if (
                row["status"] == "failed"
                and event["stage"] == "answer"
                and raw.exists()
            ):
                findings[-1]["cached_response_classification"] = classify(
                    load(raw)
                ).model_dump()
    return {
        "status": "recorded_failures_reproduced_as_diagnostics",
        "findings": findings,
        "calendar_regression": date_interval("2023-04-15", "2023-04-21"),
        "note": "Postmortem uses historical labels; no answer generation or semantic retrieval accuracy claim",
        "network_calls": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "plan",
            "validate",
            "index",
            "execute",
            "resume",
            "grade",
            "status",
            "summarize",
            "approve-policy",
            "authorize-evaluation",
            "training-data",
            "training-plan",
            "training-validate",
            "training-upload",
            "training-submit",
            "training-status",
            "training-cancel",
            "training-checkpoints",
            "readiness",
            "audit",
            "compare-checkpoint",
        ],
    )
    parser.add_argument("--data", default="tests/fixtures/longmemeval_synthetic.json")
    parser.add_argument("--profile")
    parser.add_argument("--base-report")
    parser.add_argument("--trained-report")
    parser.add_argument("--output", default=".benchmark-artifacts/pipeline-plan")
    parser.add_argument("--plan")
    parser.add_argument("--approval")
    parser.add_argument("--confirm-plan-sha")
    parser.add_argument("--confirm-cost-usd")
    parser.add_argument("--approval-reference")
    parser.add_argument("--approved-by", default="local operator")
    parser.add_argument(
        "--launch-strategy",
        choices=["validated", "full_baseline"],
        default="validated",
        help="full_baseline permits an approved full evaluation without a short pilot; quality is unvalidated",
    )
    parser.add_argument(
        "--validation-report",
        help="Frozen held-out live protocol report required before a full paid run",
    )
    parser.add_argument("--job", default=".benchmark-artifacts/training-job.json")
    parser.add_argument("--api-key-env", default="NEBIUS_API_KEY")
    parser.add_argument(
        "--examples-file",
        help="Reviewed TrainingExample JSON array or JSONL; not benchmark labels",
    )
    parser.add_argument("--synthetic-groups", type=int, default=24)
    parser.add_argument(
        "--capability", default="config/training-capability.nebius.json"
    )
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=0.00001)
    parser.add_argument("--context-tokens", type=int, default=8192)
    parser.add_argument("--training-method", choices=["lora", "full"], default="lora")
    parser.add_argument("--maximum-liability-usd")
    parser.add_argument(
        "--training-costs-file",
        help="Verified complete cost-component JSON, including hosting/evaluation",
    )
    parser.add_argument("--artifact-root", default=".benchmark-artifacts")
    parser.add_argument("--run-dir", default=".benchmark-artifacts/pipeline-run")
    parser.add_argument("--experiment-id", default="memory-evaluation")
    parser.add_argument(
        "--dataset-profile",
        choices=["synthetic", "oracle", "s_cleaned"],
        default="synthetic",
    )
    parser.add_argument(
        "--mode",
        choices=["direct", "hermes", "compare", "application", "retrieval-only"],
        default="retrieval-only",
    )
    parser.add_argument(
        "--split", choices=["all", "development", "heldout"], default="all"
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--neighbors", type=int, default=1)
    parser.add_argument("--max-cost-usd", default="1")
    parser.add_argument("--max-calls", type=int, default=100)
    parser.add_argument("--reserve-usd", default="20")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--benchmarks", nargs="*", default=[])
    parser.add_argument("--revoked-sources", nargs="*", default=[])
    options = parser.parse_args(argv)
    command = options.command
    if command == "compare-checkpoint":
        from scripts._checkpoint_evaluation import compare_reports

        if not options.plan or not options.base_report or not options.trained_report:
            parser.error(
                "Requires --plan comparison contract, --base-report and --trained-report"
            )
        result = compare_reports(
            load(options.base_report), load(options.trained_report), load(options.plan)
        )
        atomic_json(Path(options.output) / "checkpoint-comparison.json", result)
    elif command == "authorize-evaluation":
        from datetime import datetime, timedelta, timezone

        if (
            not options.plan
            or not options.confirm_plan_sha
            or options.confirm_cost_usd is None
            or not options.approval_reference
        ):
            parser.error(
                "Requires --plan, --confirm-plan-sha, --confirm-cost-usd and --approval-reference"
            )
        plan = EvaluationPlan.model_validate(load(options.plan))
        validate_plan(plan)
        if options.confirm_plan_sha != plan.fingerprint or money_units(
            options.confirm_cost_usd
        ) != money_units(plan.cost.cumulative_cap_usd):
            raise ValueError(
                "Explicit confirmation does not match the frozen plan/cumulative cap"
            )
        target = (
            Path(options.approval)
            if options.approval
            else Path(options.plan).with_name("approval.json")
        )
        if target.exists():
            raise ValueError(
                "Approval file already exists; preserve it and choose a new output path"
            )
        now = datetime.now(timezone.utc)
        approval = Approval(
            action="evaluation",
            plan_sha256=plan.fingerprint,
            approved_by=options.approved_by,
            approved_at=now.isoformat(),
            expires_at=(now + timedelta(hours=24)).isoformat(),
            approval_reference=options.approval_reference,
        )
        atomic_json(target, approval.model_dump(mode="json"))
        result = {
            "approval_file": str(target),
            "plan_sha256": plan.fingerprint,
            "cap_usd": plan.cost.cumulative_cap_usd,
            "network_calls": 0,
            "ledger_allocation_changed": False,
        }
    elif command == "plan":
        result = plan_evaluation(options)
    elif command == "audit":
        result = audit_recorded_failures(options.artifact_root)
        atomic_json(Path(options.output) / "failure-audit.json", result)
    elif command == "readiness":
        result = readiness()
    elif command == "training-data":
        from scripts._training_pipeline import independent_examples, prepare_training

        if options.examples_file:
            if not options.benchmarks:
                parser.error(
                    "Custom training data requires --benchmarks for contamination checks"
                )
            content = Path(options.examples_file).read_text(encoding="utf-8")
            examples = (
                json.loads(content)
                if content.lstrip().startswith("[")
                else [json.loads(line) for line in content.splitlines() if line.strip()]
            )
        else:
            if not 3 <= options.synthetic_groups <= 10000:
                parser.error("synthetic-groups must be between 3 and 10000")
            examples = [
                row.model_dump()
                for row in independent_examples(
                    groups=options.synthetic_groups, seed=options.seed
                )
            ]
        benchmarks = [row for source in options.benchmarks for row in load(source)]
        result = prepare_training(
            examples,
            options.output,
            benchmarks=benchmarks,
            revoked_sources=options.revoked_sources,
            seed=options.seed,
        )
    elif command.startswith("training-") and command not in {
        "training-plan",
        "training-data",
    }:
        import os

        import httpx

        from scripts._training_pipeline import (
            NebiusTrainingAdapter,
            TrainingJob,
            TrainingPlan,
        )

        if not options.plan:
            parser.error("Training operation requires --plan")
        raw = load(options.plan)
        training = TrainingPlan.model_validate(raw.get("plan", raw))
        manifest = load(Path(options.data) / "manifest.json")
        if digest(manifest) != training.dataset_manifest_sha256:
            raise ValueError("Training dataset manifest differs from plan")
        if command == "training-validate":
            for name in ("train", "validation", "test"):
                records = [
                    json.loads(line)
                    for line in (Path(options.data) / f"{name}.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line
                ]
                if digest(records) != manifest["artifacts"][name]["sha256"]:
                    raise ValueError("Training artifact mismatch")
            job = TrainingJob(plan_sha256=training.fingerprint)
            job.transition("DATA_VALIDATED")
            if not training.blockers():
                job.transition("READY_FOR_APPROVAL")
            if Path(options.job).exists():
                raise ValueError(
                    "Job artifact already exists; never reset an existing job"
                )
            atomic_json(options.job, job.model_dump(mode="json"))
            result = {
                "job": job.model_dump(mode="json"),
                "blockers": training.blockers(),
                "network_calls": 0,
            }
        else:
            if not options.live:
                raise ValueError(
                    "Training HTTP operations require explicit --live and applicable approval"
                )
            if training.blockers():
                raise ValueError("; ".join(training.blockers()))
            job = TrainingJob.model_validate(load(options.job))
            if job.plan_sha256 != training.fingerprint:
                raise ValueError("Training job plan mismatch")
            action = (
                "training_upload" if command == "training-upload" else "training_submit"
            )
            if not options.approval:
                parser.error("Requires action-specific --approval")
            consent = Approval.model_validate(load(options.approval))
            consent.require(action, training.fingerprint)
            key = os.getenv(options.api_key_env)
            if not key:
                raise ValueError("Missing private training key environment variable")
            current = ledger_snapshot(options.artifact_root)
            ledger = Ledger(
                Path(options.artifact_root) / "budget.sqlite3",
                current.get("cap_usd", "1"),
                current.get("call_cap", 100),
            )
            from scripts._experiment_store import exclusive_path

            with exclusive_path(Path(options.job).with_suffix(".lock")):
                with httpx.Client(
                    timeout=60,
                    follow_redirects=False,
                    headers={"Authorization": "Bearer " + key},
                ) as client:
                    adapter = NebiusTrainingAdapter(client, ledger)
                    if command == "training-upload":
                        adapter.upload(
                            training,
                            job,
                            options.job,
                            Path(options.data) / "train.jsonl",
                            Path(options.data) / "validation.jsonl",
                            consent,
                        )
                    elif command == "training-submit":
                        adapter.submit(training, job, options.job, consent)
                    elif command == "training-cancel":
                        adapter.cancel(job, options.job, consent, training)
                    elif command == "training-status":
                        adapter.refresh(job, options.job)
                    else:
                        result = adapter.checkpoints(job)
                        atomic_json(Path(options.output) / "checkpoints.json", result)
                if command != "training-checkpoints":
                    result = {
                        "job": job.model_dump(mode="json"),
                        "ledger": ledger.summary(),
                    }
    elif command == "training-plan":
        from scripts._training_pipeline import TrainingCapability, TrainingPlan

        manifest = load(Path(options.data) / "manifest.json")
        capability = TrainingCapability.model_validate(load(options.capability))
        plan = TrainingPlan(
            model=capability.model,
            capability=capability,
            dataset_manifest_sha256=digest(manifest),
            train_file_sha256=manifest["artifacts"]["train"]["sha256"],
            validation_file_sha256=manifest["artifacts"]["validation"]["sha256"],
            epochs=options.epochs,
            batch_size=options.batch_size,
            learning_rate=options.learning_rate,
            context_tokens=options.context_tokens,
            method=options.training_method,
            maximum_liability_usd=options.maximum_liability_usd,
            cost_components=load(options.training_costs_file)
            if options.training_costs_file
            else {},
        )
        result = {
            "plan": plan.model_dump(mode="json"),
            "plan_sha256": plan.fingerprint,
            "blockers": plan.blockers(),
            "network_calls": 0,
        }
        atomic_json(Path(options.output) / "training-plan.json", result)
    elif command in {"status", "summarize"}:
        report_path = Path(options.run_dir) / "report.json"
        result = {
            "ledger": ledger_snapshot(options.artifact_root),
            "report": load(report_path) if report_path.exists() else None,
        }
    else:
        if not options.plan:
            parser.error("This command requires --plan")
        plan = EvaluationPlan.model_validate(load(options.plan))
        rows, profile = validate_plan(plan)
        if command == "validate":
            result = {
                "valid": True,
                "plan_sha256": plan.fingerprint,
                "questions": len(plan.question_ids),
                "network_calls": 0,
            }
        elif command == "approve-policy":
            if not options.approval:
                parser.error("Requires a completed explicit --approval record")
            approval = Approval.model_validate(load(options.approval))
            current = ledger_snapshot(options.artifact_root)
            # Opening the original pilot policy does not change existing limits.
            ledger = Ledger(
                Path(options.artifact_root) / "budget.sqlite3",
                max_calls=max(100, current["calls"]),
            )
            ledger.approve_policy(plan, approval)
            result = ledger.summary()
        elif command == "index":
            if (
                options.live
                or options.replay
                or profile.get("embedding", {}).get("backend", "hash-test")
                != "hash-test"
            ):
                raise ValueError(
                    "Standalone index is offline hash-only; authorized semantic indexing occurs through execute/resume"
                )
            from scripts._benchmark_runtime import isolated_settings
            from scripts._experiment_store import instance_store

            traces = []
            for row in rows:
                if row["question_id"] in plan.question_ids:
                    with instance_store(
                        row,
                        isolated_settings(
                            database_url="sqlite://", cloud_disclosure_enabled=False
                        ),
                        {},
                        profile,
                        options.artifact_root,
                    ) as (_, _, _, _, trace):
                        traces.append(trace)
            result = {"indexes": traces, "network_calls": 0}
            atomic_json(Path(options.output) / "index-report.json", result)
        else:
            if command == "grade":
                report = load(Path(options.run_dir) / "report.json")
                expected = {
                    (qid, mode) for qid in plan.question_ids for mode in plan.modes
                }
                actual = {
                    (row["question_id"], row["mode"])
                    for row in report["questions_detail"]
                }
                if expected != actual:
                    raise ValueError(
                        "Grade-only requires a saved record for every planned instance/mode"
                    )
                missing = [
                    r
                    for r in report["questions_detail"]
                    if r.get("attempted")
                    and "prediction" not in r
                    and r["status"] != "retrieved"
                ]
                if missing:
                    raise ValueError(
                        "Grade-only cannot regenerate missing answers; use resume explicitly"
                    )
            result = execute_plan(plan, options)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return result


if __name__ == "__main__":
    main()
