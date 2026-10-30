import copy
import json

import httpx
import pytest

from scripts._benchmark_runtime import Ledger, atomic_json, digest
from scripts._experiment_contracts import CostPlan, EvaluationPlan
from scripts._longmemeval_harness import ROOT
from scripts._training_pipeline import (
    NebiusTrainingAdapter,
    independent_examples,
    prepare_training,
)
from scripts.experiment_pipeline import (
    estimate,
    remaining_cost_bound,
    validate_protocol_gate,
)
from tests.unit.test_experiment_pipeline import approval, prepared_job, training_plan


def test_direct_full_run_is_an_explicit_frozen_strategy():
    common = dict(
        experiment_id="full",
        dataset_path="unused",
        dataset_sha256="d",
        profile_sha256="p",
        code_sha256="c",
        question_ids=[f"q{i}" for i in range(500)],
        modes=["direct"],
        split="all",
        dataset_profile="oracle",
        cost=CostPlan(),
    )
    validated = EvaluationPlan(**common)
    with pytest.raises(ValueError, match="held-out"):
        validate_protocol_gate(validated)
    baseline = EvaluationPlan(**common, launch_strategy="full_baseline")
    validate_protocol_gate(baseline)
    assert baseline.fingerprint != validated.fingerprint


def test_resume_cost_counts_only_unfinished_judge(tmp_path):
    from datetime import date

    instance = json.loads(
        (ROOT / "tests/fixtures/longmemeval_synthetic.json").read_text(encoding="utf-8")
    )[0]
    route = {
        "model": "nvidia/synthetic-fixture",
        "base_url": "https://api.tokenfactory.nebius.com/v1",
        "api_key_env": "UNUSED",
        "bounded_output_verified": True,
        "pricing": {
            "input": "1",
            "output": "1",
            "currency": "USD",
            "unit": "per_million_tokens",
            "verified_on": date.today().isoformat(),
            "source_url": "https://nebius.com/fixture",
            "output_includes_reasoning": True,
        },
    }
    profile = {"answer": route, "judge": route}
    atomic_json(tmp_path / "data.json", [instance])
    atomic_json(tmp_path / "profile.json", profile)
    plan = EvaluationPlan(
        experiment_id="resume",
        dataset_path=str(tmp_path / "data.json"),
        dataset_sha256=digest([instance]),
        profile_path=str(tmp_path / "profile.json"),
        profile_sha256=digest(profile),
        code_sha256="fixture",
        question_ids=[instance["question_id"]],
        modes=["direct"],
        split="all",
        dataset_profile="synthetic",
        cost=CostPlan(upper_bound_usd="0.9"),
    )
    assert remaining_cost_bound(plan, tmp_path / "run") == "0.9"
    report = {
        "manifest": {"evaluation_plan_sha256": plan.fingerprint},
        "questions_detail": [
            {
                "question_id": instance["question_id"],
                "mode": "direct",
                "status": "answered",
                "prediction": "14 days",
            }
        ],
    }
    atomic_json(tmp_path / "run/report.json", report)
    assert (
        remaining_cost_bound(plan, tmp_path / "run")
        == estimate([instance], profile, ["direct"])["stage_costs"]["judge"]
    )
    report["questions_detail"][0]["status"] = "graded"
    atomic_json(tmp_path / "run/report.json", report)
    assert remaining_cost_bound(plan, tmp_path / "run") == "0"
    report["manifest"]["evaluation_plan_sha256"] = "wrong"
    atomic_json(tmp_path / "run/report.json", report)
    with pytest.raises(ValueError, match="different"):
        remaining_cost_bound(plan, tmp_path / "run")


def test_training_context_overflow_rejected_before_any_reservation_or_http(tmp_path):
    manifest = prepare_training(
        [row.model_dump() for row in independent_examples()], tmp_path / "data"
    )
    path = tmp_path / "data/train.jsonl"
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    records[0]["messages"][0]["content"] = "oversized input " * 2000
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    manifest["artifacts"]["train"]["sha256"] = digest(records)
    plan = training_plan(manifest)
    job = prepared_job(plan)
    ledger = Ledger(tmp_path / "budget.sqlite3")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("Oversized training record reached API")
        )
    ) as client:
        adapter = NebiusTrainingAdapter(client, ledger)
        with pytest.raises(ValueError, match="context ceiling"):
            adapter.upload(
                plan,
                job,
                tmp_path / "job.json",
                path,
                tmp_path / "data/validation.jsonl",
                approval("training_upload", plan.fingerprint),
            )
    assert ledger.summary()["calls"] == 0


def test_checkpoint_comparison_rejects_changed_output_ceiling():
    from scripts._checkpoint_evaluation import compare_reports
    from scripts._experiment_contracts import ComparisonPlan

    judge = {"model": "judge"}
    common = {
        "dataset_sha256": "corpus",
        "question_ids": ["q"],
        "effective_retrieval_policy": {},
        "prompt_sha256": "p",
        "response_adapter": "strict-native-v2",
        "modes": ["direct"],
        "top_k": 20,
        "neighbors": 1,
        "preprocessing_version": "v2",
        "code": {},
        "scope": "backend",
    }
    base = {
        "manifest": {
            **common,
            "config": {
                "answer": {"model": "base"},
                "judge": judge,
                "output_tokens": 512,
            },
        },
        "questions_detail": [
            {
                "question_id": "q",
                "mode": "direct",
                "status": "graded",
                "prediction": "a",
                "correct": True,
            }
        ],
    }
    trained = copy.deepcopy(base)
    trained["manifest"]["config"]["answer"]["model"] = "trained"
    trained["manifest"]["config"]["output_tokens"] = 8192
    comparison = ComparisonPlan(
        base_model="base",
        checkpoint_model="trained",
        dataset_sha256="corpus",
        question_ids=["q"],
        effective_policy_sha256=digest({}),
        answer_prompt_sha256="p",
        response_adapter="strict-native-v2",
        judge_route_sha256=digest(judge),
    )
    with pytest.raises(ValueError, match="budget"):
        compare_reports(base, trained, comparison)


def test_rolling_storage_releases_only_generated_scratch_and_keeps_reports(tmp_path):
    from scripts._experiment_store import release_scratch

    key = "a" * 64
    index = tmp_path / "indexes" / key
    embeddings = tmp_path / "cache/embedding-instances" / key
    index.mkdir(parents=True)
    embeddings.mkdir(parents=True)
    (index / "index.sqlite3").write_bytes(b"scratch")
    (embeddings / "vector.json").write_text("{}")
    (tmp_path / "report.json").write_text("{}")
    release_scratch(tmp_path, index_fingerprint=key, embedding_key=key)
    assert not index.exists() and not embeddings.exists()
    assert (tmp_path / "report.json").exists()
    with pytest.raises(ValueError):
        release_scratch(tmp_path, index_fingerprint="../outside")
    index.mkdir(parents=True)
    (index / "owner.lock").write_text("claimed")
    with pytest.raises(ValueError, match="claimed"):
        release_scratch(tmp_path, index_fingerprint=key)


def test_repeated_session_variants_preserve_sources_and_empty_turn_indices():
    from scripts._longmemeval_harness import source_rows, validate_instances

    instance = json.loads(
        (ROOT / "tests/fixtures/longmemeval_synthetic.json").read_text(encoding="utf-8")
    )[0]
    instance.update(
        haystack_session_ids=["repeated", "repeated"],
        haystack_dates=["2024/04/15 (Mon) 09:00", "2024/04/15 (Mon) 09:00"],
        haystack_sessions=[
            [
                {"role": "user", "content": ""},
                {"role": "user", "content": "First variant"},
            ],
            [{"role": "user", "content": "Second variant"}],
        ],
        answer_session_ids=["repeated"],
    )
    validate_instances([instance])
    rows = source_rows(instance)
    assert len(rows) == 2
    assert rows[0]["turn_index"] == 1
    assert rows[0]["session_id"] == rows[1]["session_id"] == "repeated"
    assert rows[0]["session_key"] != rows[1]["session_key"]
    assert rows[0]["source_id"] != rows[1]["source_id"]
    assert rows == source_rows(instance)
    instance["haystack_sessions"][0][1]["has_answer"] = True
    assert rows == source_rows(instance)
    instance["haystack_sessions"][0][0]["content"] = None
    with pytest.raises(ValueError, match="must be text"):
        validate_instances([instance])


def test_operator_approval_confirms_exact_plan_without_changing_ledger(tmp_path):
    from scripts.experiment_pipeline import main

    root = tmp_path / "plan"
    result = main(["plan", "--output", str(root), "--mode", "retrieval-only"])
    args = [
        "authorize-evaluation",
        "--plan",
        str(root / "plan.json"),
        "--confirm-plan-sha",
        result["plan_sha256"],
        "--confirm-cost-usd",
        "2",
        "--approval-reference",
        "unit test",
    ]
    with pytest.raises(ValueError, match="does not match"):
        main(args)
    assert not (root / "approval.json").exists()
    args[args.index("--confirm-cost-usd") + 1] = "1"
    approved = main(args)
    assert approved["network_calls"] == 0
    assert approved["ledger_allocation_changed"] is False
    assert (root / "approval.json").exists()
    with pytest.raises(ValueError, match="already exists"):
        main(args)
