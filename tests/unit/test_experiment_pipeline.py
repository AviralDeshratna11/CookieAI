import copy
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from memory.policy import Policy
from memory.schemas import MemoryCreate
from memory.security.auth import AccessDenied
from memory.service import MemoryService
from models.providers import HashEmbedding
from scripts._benchmark_runtime import (
    Ledger,
    atomic_json,
    digest,
    isolated_settings,
    money_units,
)
from scripts._benchmark_tools import EvidenceTools, date_interval, supported_event_dates
from scripts._experiment_contracts import (
    Approval,
    Checkpoint,
    CostPlan,
    EvaluationPlan,
    SourceRecord,
)
from scripts._experiment_store import instance_store
from scripts._longmemeval_harness import (
    ROOT,
    NoExtractor,
    execute_in_instance,
    ingest,
    select_instances,
    source_rows,
)
from scripts._response_adapter import classify
from scripts._training_pipeline import (
    NebiusTrainingAdapter,
    TrainingCapability,
    TrainingExample,
    TrainingJob,
    TrainingPlan,
    independent_examples,
    prepare_training,
    promotion_plan,
)
from scripts.experiment_pipeline import main as controller


def completion(content="6 days", calls=None, finish="stop"):
    return {
        "id": "fixture",
        "object": "chat.completion",
        "created": 0,
        "model": "fixture",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": calls,
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@pytest.fixture
def instance():
    return json.loads(
        (ROOT / "tests/fixtures/longmemeval_synthetic.json").read_text(encoding="utf-8")
    )[0]


def approval(action, fingerprint):
    now = datetime.now(timezone.utc)
    return Approval(
        action=action,
        plan_sha256=fingerprint,
        approved_by="offline-test-only",
        approval_reference="synthetic approval fixture",
        approved_at=(now - timedelta(minutes=1)).isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
    )


def evaluation_plan(cap="1", calls=100):
    return EvaluationPlan(
        experiment_id="fixture",
        dataset_path="unused",
        dataset_sha256="fixture",
        profile_sha256="fixture",
        code_sha256="fixture",
        question_ids=["synthetic_fixture"],
        modes=["direct"],
        split="all",
        dataset_profile="synthetic",
        cost=CostPlan(cumulative_cap_usd=cap, max_calls=calls),
    )


def test_policy_override_isolated_from_file_and_hostile_environment(
    engine, monkeypatch, ctx
):
    monkeypatch.setenv("MEMORY_MAX_MEMORY_TOKENS", "1")
    monkeypatch.setenv("MEMORY_SCORING_WEIGHTS", "not-a-dict")
    service = MemoryService(
        engine,
        HashEmbedding(),
        NoExtractor(),
        isolated_settings(),
        policy_override=Policy(max_memory_tokens=12000),
    )
    assert service.policy(None).max_memory_tokens == 12000
    service.create(ctx, MemoryCreate(text="Private benchmark fixture"))
    from memory.schemas import SearchRequest

    assert service.search(ctx, SearchRequest(query="Private benchmark fixture"))


def test_retrieval_reports_budget_and_rank_exclusions(service, ctx):
    from memory.retrieval.hybrid import diverse_select
    from memory.schemas import SearchRequest

    memories = [
        service.create(ctx, MemoryCreate(text="bounded test text " + str(i)))
        for i in range(3)
    ]
    trace = {}
    assert not diverse_select([(m, 1.0, {}) for m in memories], 1, 1, trace=trace)
    assert all(item["status"] == "retrieval_budget_excluded" for item in trace.values())
    trace = {}
    diverse_select([(m, 1.0, {}) for m in memories], 1, 100000, trace=trace)
    assert sorted(item["status"] for item in trace.values()) == [
        "ranked_out",
        "ranked_out",
        "selected",
    ]
    observations = []
    service.search_observer = observations.append
    service.search(ctx, SearchRequest(query="bounded"))
    assert observations[0]["namespace_id"] == str(ctx.namespace_id)
    assert observations[0]["selection"]


def test_source_chunks_reassemble_exact_text_and_keep_repeat_provenance(instance):
    text = "  Exact unicode café\n" * 180
    instance["haystack_sessions"][0][0]["content"] = text
    rows = source_rows(instance)
    chunks = [
        row
        for row in rows
        if row["session_id"] == "bike_order" and row["turn_index"] == 0
    ]
    assert "".join(row["text"] for row in chunks) == text
    assert max(len(row["text"]) for row in chunks) <= 1200
    for row in chunks:
        SourceRecord.model_validate(row)
    changed = copy.deepcopy(instance)
    changed["haystack_session_ids"][0] = "different-session"
    assert source_rows(changed)[0]["source_id"] != rows[0]["source_id"]


@pytest.mark.parametrize(
    "start,end,elapsed,inclusive",
    [
        ("2024-02-28", "2024-03-01", 2, 3),
        ("2023-12-31", "2024-01-01", 1, 2),
        ("2024-03-01", "2024-02-28", -2, -3),
        ("2024-01-01", "2024-01-01", 0, 1),
        ("2023-04-15", "2023-04-21", 6, 7),
    ],
)
def test_calendar_arithmetic(start, end, elapsed, inclusive):
    assert date_interval(start, end)["days"] == elapsed
    assert date_interval(start, end, "inclusive")["days"] == inclusive


def test_date_resolution_preserves_ambiguity():
    row = {
        "text": "I attended a workshop today.",
        "session_date": "2023/04/15 (Sat) 18:09",
    }
    assert supported_event_dates(row) == {"2023-04-15"}
    assert (
        supported_event_dates({**row, "text": "I attended last Friday in April."})
        == set()
    )
    with pytest.raises(ValueError):
        date_interval("2023-02-29", "2023-03-01")
    with pytest.raises(ValueError):
        date_interval("2023-01-01", "2023-03-01", "months")


def tools_fixture(service, ctx):
    rows = [
        {
            "source_id": "first",
            "session_id": "a",
            "session_date": "2023/04/15 (Sat) 18:09",
            "turn_index": 0,
            "chunk_index": 0,
            "role": "user",
            "text": "I attended the workshop today.",
        },
        {
            "source_id": "last",
            "session_id": "b",
            "session_date": "2023/04/21 (Fri) 20:28",
            "turn_index": 0,
            "chunk_index": 0,
            "role": "user",
            "text": "I planted seedlings today.",
        },
    ]
    return EvidenceTools(service, ctx, ingest(service, ctx, rows))


def test_evidence_tools_authorize_every_source_and_bound_loops(service, ctx):
    tools = tools_fixture(service, ctx)
    result = tools.execute(
        "benchmark_date_interval",
        {
            "start_source_id": "first",
            "start_date": "2023-04-15",
            "end_source_id": "last",
            "end_date": "2023-04-21",
        },
    )
    assert result["days"] == 6 and result["event_selection_verified"] is False
    with pytest.raises(ValueError, match="Repeated"):
        tools.execute(
            "benchmark_date_interval",
            {
                "start_source_id": "first",
                "start_date": "2023-04-15",
                "end_source_id": "last",
                "end_date": "2023-04-21",
            },
        )
    with pytest.raises(AccessDenied):
        tools.execute("benchmark_expand", {"source_id": "another-instance"})
    with pytest.raises(ValueError):
        tools.execute(
            "benchmark_search", {"query": "workshop", "namespace_id": str(uuid4())}
        )
    source_mid = next(
        mid for mid, rows in tools.mapping.items() if rows[0]["source_id"] == "last"
    )
    from uuid import UUID

    service.delete(ctx, UUID(source_mid))
    with pytest.raises(Exception):
        tools.get_source("last")


def test_index_resume_reuses_completed_sources_and_rejects_ambient_policy(
    tmp_path, instance, monkeypatch
):
    monkeypatch.setenv("MEMORY_MAX_MEMORY_TOKENS", "1")
    settings = isolated_settings(
        database_url="sqlite://", cloud_disclosure_enabled=False
    )
    with instance_store(instance, settings, {}, {}, tmp_path) as (
        _,
        _,
        mapping,
        _,
        trace,
    ):
        assert len(mapping) == 3 and trace["sources_created"] == 3
    with instance_store(instance, settings, {}, {}, tmp_path) as (
        _,
        _,
        mapping,
        _,
        trace2,
    ):
        assert trace2["sources_created"] == 0 and trace2["sources_reused"] == 3
        assert trace2["fingerprint"] == trace["fingerprint"]
    with instance_store(
        instance,
        settings,
        {},
        {"retrieval_policy": {"max_memory_tokens": 15000}},
        tmp_path,
    ) as (_, _, _, _, changed):
        assert changed["fingerprint"] != trace["fingerprint"]


@pytest.mark.parametrize(
    "body,state",
    [
        (completion("6 days"), "final"),
        (completion(None), "malformed"),
        (completion("unfinished", finish="length"), "length_truncated"),
        (completion("reasoning</think>6 days"), "mixed_reasoning_final"),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": None, "reasoning_content": "private"},
                    }
                ]
            },
            "reasoning_only",
        ),
        (completion("denied", finish="content_filter"), "refusal"),
        (completion("maybe", finish=None), "incomplete"),
    ],
)
def test_response_adapter_states(body, state):
    result = classify(body)
    assert result.state == state
    assert result.final is None if state != "final" else result.final == "6 days"


def test_request_claim_serializes_duplicates_and_retains_ambiguity(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    started, release = threading.Event(), threading.Event()

    def claimed():
        with ledger.request_claim("same"):
            started.set()
            release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(claimed)
        assert started.wait(5)
        with pytest.raises(RuntimeError, match="claimed"):
            with ledger.request_claim("same"):
                pytest.fail("Duplicate request escaped claim")
        release.set()
        future.result()
    with pytest.raises(TimeoutError):
        with ledger.request_claim("ambiguous"):
            ledger.reserve("answer", "ambiguous", 10)
            raise TimeoutError
    with pytest.raises(RuntimeError):
        with ledger.request_claim("ambiguous"):
            pass
    assert ledger.summary()["spent_or_reserved_usd"] == "1E-8"


def test_policy_migration_keeps_prior_requests_and_binds_approval(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.reserve("answer", "prior", money_units("0.1"))
    plan = evaluation_plan("5", 500)
    with pytest.raises(ValueError):
        Ledger(tmp_path / "ledger.sqlite3", "5", 500)
    with pytest.raises(ValueError):
        ledger.approve_policy(plan, approval("evaluation", "wrong"))
    ledger.approve_policy(plan, approval("evaluation", plan.fingerprint))
    reopened = Ledger(tmp_path / "ledger.sqlite3", "5", 500)
    assert reopened.summary()["calls"] == 1
    assert reopened.summary()["spent_or_reserved_usd"] == "0.1"
    assert reopened.summary()["cap_usd"] == "5"
    with pytest.raises(ValueError):
        CostPlan(cumulative_cap_usd="10", reserve_usd="20")


def test_full_selection_covers_all_ids_and_offline_controller(
    tmp_path, instance, monkeypatch
):
    monkeypatch.setattr(
        httpx.Client,
        "send",
        lambda *a, **k: pytest.fail("Offline command made HTTP request"),
    )
    rows = [{**instance, "question_id": f"synthetic_{i}"} for i in range(500)]
    chosen, held = select_instances(rows, 500, split="all")
    assert len(chosen) == 500 and not held
    data = tmp_path / "data.json"
    atomic_json(data, rows[:3])
    root = tmp_path / "plan"
    result = controller(
        [
            "plan",
            "--data",
            str(data),
            "--output",
            str(root),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )
    assert result["questions"] == 3 and result["network_calls"] == 0
    assert controller(["validate", "--plan", str(root / "plan.json")])["valid"]
    index = controller(
        [
            "index",
            "--plan",
            str(root / "plan.json"),
            "--output",
            str(root),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )
    assert len(index["indexes"]) == 3
    report = controller(
        [
            "execute",
            "--plan",
            str(root / "plan.json"),
            "--run-dir",
            str(tmp_path / "run"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )
    assert report["status_counts"] == {"retrieved": 3}


def test_training_groups_leakage_revocation_and_no_private_reasoning(
    tmp_path, instance
):
    examples = [row.model_dump() for row in independent_examples()]
    examples[0]["source_ids"] = [instance["haystack_session_ids"][0]]
    examples[1]["source_ids"] = ["revoked"]
    examples[3]["source_ids"].append("shared-lineage")
    examples[4]["source_ids"].append("shared-lineage")
    manifest = prepare_training(
        examples, tmp_path, benchmarks=[instance], revoked_sources=["revoked"]
    )
    assert len(manifest["excluded"]) == 2
    affected = {
        row["split"]
        for row in manifest["examples"]
        if "shared-lineage" in row["sources"]
    }
    assert len(affected) == 1
    for partition in ("train", "validation", "test"):
        assert manifest["artifacts"][partition]["examples"] > 0
        for line in (
            (tmp_path / f"{partition}.jsonl").read_text(encoding="utf-8").splitlines()
        ):
            record = json.loads(line)
            assert "schema_version" not in record["messages"][0]
    bad = copy.deepcopy(examples[2])
    bad["messages"][-1]["content"] = "<think>private</think>answer"
    with pytest.raises(ValueError):
        TrainingExample.model_validate(bad)


def training_plan(manifest, supported=True):
    capability = TrainingCapability(
        model="synthetic-base",
        supported=supported,
        account_verified=supported,
        schema_verified=True,
        credit_eligibility_verified=True,
        methods=["lora", "full"],
        source_url="https://docs.tokenfactory.nebius.com/post-training/models",
        checked_on="2026-10-29",
        pricing_verified=True,
        max_context_tokens=8192,
    )
    return TrainingPlan(
        model="synthetic-base",
        capability=capability,
        dataset_manifest_sha256=digest(manifest),
        train_file_sha256=manifest["artifacts"]["train"]["sha256"],
        validation_file_sha256=manifest["artifacts"]["validation"]["sha256"],
        maximum_liability_usd="0.5",
        cost_components={"training": "0.3", "storage_upload_serving_evaluation": "0.2"},
    )


def prepared_job(plan):
    job = TrainingJob(plan_sha256=plan.fingerprint)
    job.transition("DATA_VALIDATED")
    job.transition("READY_FOR_APPROVAL")
    return job


def test_training_lifecycle_uses_supported_mapping_and_preserves_liability(tmp_path):
    manifest = prepare_training(
        [row.model_dump() for row in independent_examples()], tmp_path / "data"
    )
    plan = training_plan(manifest)
    job = prepared_job(plan)
    calls = []

    def transport(request):
        calls.append(request)
        if request.url.path == "/v1/files":
            assert b"fine-tune" in request.content
            return httpx.Response(200, json={"id": f"file-{len(calls)}"})
        if request.url.path == "/v1/fine_tuning/jobs":
            data = json.loads(request.content)
            assert (
                data["model"] == "synthetic-base"
                and data["hyperparameters"]["lora"] is True
            )
            return httpx.Response(200, json={"id": "job-1"})
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"status": "cancelling"})
        return httpx.Response(200, json={"status": "cancelled"})

    ledger = Ledger(tmp_path / "ledger.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = NebiusTrainingAdapter(client, ledger)
        state = tmp_path / "job.json"
        adapter.upload(
            plan,
            job,
            state,
            tmp_path / "data/train.jsonl",
            tmp_path / "data/validation.jsonl",
            approval("training_upload", plan.fingerprint),
        )
        adapter.submit(plan, job, state, approval("training_submit", plan.fingerprint))
        assert job.state == "QUEUED"
        with pytest.raises(ValueError):
            adapter.submit(
                plan, job, state, approval("training_submit", plan.fingerprint)
            )
        adapter.cancel(job, state, approval("training_submit", plan.fingerprint), plan)
        assert job.state == "CANCEL_REQUESTED"
        assert ledger.summary()["spent_or_reserved_usd"] == "0.5"
        adapter.refresh(job, state)
        assert job.state == "CANCELLED"
        adapter.reconcile_liability(
            job, "0.1", "synthetic authoritative fixture invoice"
        )
        assert ledger.summary()["spent_or_reserved_usd"] == "0.1"


def test_training_unknown_submission_cannot_be_retried(tmp_path):
    manifest = prepare_training(
        [row.model_dump() for row in independent_examples()], tmp_path / "data"
    )
    plan = training_plan(manifest)
    job = prepared_job(plan)
    ledger = Ledger(tmp_path / "ledger.sqlite3")

    def transport(request):
        if request.url.path == "/v1/files":
            return httpx.Response(200, json={"id": "file-test"})
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = NebiusTrainingAdapter(client, ledger)
        path = tmp_path / "job.json"
        adapter.upload(
            plan,
            job,
            path,
            tmp_path / "data/train.jsonl",
            tmp_path / "data/validation.jsonl",
            approval("training_upload", plan.fingerprint),
        )
        with pytest.raises(httpx.ReadTimeout):
            adapter.submit(
                plan, job, path, approval("training_submit", plan.fingerprint)
            )
        assert job.state == "UNKNOWN"
        with pytest.raises(ValueError):
            adapter.submit(
                plan, job, path, approval("training_submit", plan.fingerprint)
            )
    assert ledger.summary()["spent_or_reserved_usd"] == "0.5"


def test_training_capability_gate_blocks_without_network(tmp_path):
    manifest = prepare_training(
        [row.model_dump() for row in independent_examples()], tmp_path / "data"
    )
    plan = training_plan(manifest, supported=False)
    job = prepared_job(plan)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: pytest.fail("Unsupported training attempted HTTP")
        )
    ) as client:
        adapter = NebiusTrainingAdapter(client, Ledger(tmp_path / "ledger.sqlite3"))
        with pytest.raises(ValueError, match="unsupported_model_or_account"):
            adapter.upload(
                plan,
                job,
                tmp_path / "job.json",
                tmp_path / "data/train.jsonl",
                tmp_path / "data/validation.jsonl",
                approval("training_upload", plan.fingerprint),
            )


def test_redaction_excludes_unreviewed_targets_and_revocation_propagates(tmp_path):
    examples = [row.model_dump() for row in independent_examples()]
    examples[0]["origin"] = "consented_corpus"
    examples[0]["messages"][0]["content"] = (
        "Contact person@example.test on 2024-02-29 or +1 555 234 5678."
    )
    examples[1]["source_ids"] = ["removed", "linked"]
    examples[2]["source_ids"] = ["linked"]
    manifest = prepare_training(examples, tmp_path, revoked_sources=["removed"])
    assert len(manifest["excluded"]) == 3
    redacted = (tmp_path / "redacted-review.json").read_text(encoding="utf-8")
    assert "person@example.test" not in redacted and "+1 555" not in redacted
    assert "2024-02-29" in redacted and "REDACTED_EMAIL" in redacted


def test_training_duplicate_plan_cannot_create_second_upload_job(tmp_path):
    manifest = prepare_training(
        [row.model_dump() for row in independent_examples()], tmp_path / "data"
    )
    plan = training_plan(manifest)
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "file-fixture"})

    ledger = Ledger(tmp_path / "ledger.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = NebiusTrainingAdapter(client, ledger)
        adapter.upload(
            plan,
            prepared_job(plan),
            tmp_path / "job1.json",
            tmp_path / "data/train.jsonl",
            tmp_path / "data/validation.jsonl",
            approval("training_upload", plan.fingerprint),
        )
        with pytest.raises(ValueError, match="already started"):
            adapter.upload(
                plan,
                prepared_job(plan),
                tmp_path / "job2.json",
                tmp_path / "data/train.jsonl",
                tmp_path / "data/validation.jsonl",
                approval("training_upload", plan.fingerprint),
            )
    assert len(calls) == 2 and ledger.summary()["spent_or_reserved_usd"] == "0.5"


def test_checkpoint_binding_and_promotion_require_matching_evaluation(tmp_path):
    plan = evaluation_plan()
    checkpoint = Checkpoint(
        base_model="base-fixture",
        job_id="job-fixture",
        checkpoint_id="checkpoint-fixture",
        artifact_sha256="a" * 64,
        inference_model="trained-fixture",
        evaluation_plan_sha256=plan.fingerprint,
    )
    job = TrainingJob(
        plan_sha256="training-fixture", state="SUCCEEDED", provider_job_id="job-fixture"
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"data": []})
        )
    ) as client:
        adapter = NebiusTrainingAdapter(client, Ledger(tmp_path / "ledger.sqlite3"))
        adapter.bind_checkpoint(job, tmp_path / "job.json", checkpoint)
        assert adapter.checkpoints(job) == {"data": []}
        assert adapter.events(job) == {"data": []}
    with pytest.raises(ValueError, match="provenance"):
        promotion_plan(
            checkpoint,
            {"model": "base-fixture"},
            {"manifest": {}, "completion_rate": 1},
        )
    review = promotion_plan(
        checkpoint,
        {"model": "base-fixture"},
        {
            "manifest": {"evaluation_plan_sha256": plan.fingerprint},
            "completion_rate": 0.9,
        },
    )
    assert not review["eligible_for_review"] and not review["production_changed"]
    assert review["rollback_route"]["model"] == "base-fixture"


def test_small_local_cap_still_applies_after_approved_parent_increase(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    plan = evaluation_plan("5", 500)
    ledger.approve_policy(plan, approval("evaluation", plan.fingerprint))
    limited = Ledger(tmp_path / "ledger.sqlite3", "1", 100)
    from scripts._benchmark_runtime import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        limited.reserve("answer", "too-large", money_units("1.1"))


def test_grade_only_cannot_generate_missing_planned_records(tmp_path, instance):
    data = tmp_path / "data.json"
    atomic_json(data, [instance])
    root = tmp_path / "plan"
    controller(
        [
            "plan",
            "--data",
            str(data),
            "--output",
            str(root),
            "--mode",
            "direct",
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )
    atomic_json(tmp_path / "run/report.json", {"questions_detail": []})
    with pytest.raises(ValueError, match="saved record"):
        controller(
            [
                "grade",
                "--plan",
                str(root / "plan.json"),
                "--run-dir",
                str(tmp_path / "run"),
                "--artifact-root",
                str(tmp_path / "artifacts"),
            ]
        )


def test_real_hermes_date_tool_and_application_route(tmp_path, instance):
    python = (
        ROOT
        / ".hermes-runtime/venv"
        / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    source = (
        ROOT
        / ".hermes-runtime/source/hermes-agent-1f6efd6eb0ba6b573c73c96d14dff1be4454823d"
    )
    if not python.exists() or not source.exists():
        pytest.skip("Pinned Hermes runtime unavailable")
    settings = isolated_settings(
        database_url="sqlite://",
        hermes_python=python,
        hermes_source=source,
        hermes_max_iterations=4,
        hermes_timeout_seconds=60,
        extraction_model="fixture",
        assistant_output_tokens=512,
        cloud_disclosure_enabled=False,
    )
    # Exercise AgentService submission/context transfer/real broker/final retention.
    calls = []

    class Scripted:
        def post(self, endpoint, payload):
            calls.append(payload)
            assert "question_type" not in str(payload["messages"])
            assert any(
                tool["function"]["name"] == "benchmark_date_interval"
                for tool in payload["tools"]
            )
            if len(calls) == 1:
                rows = source_rows(instance)
                return completion(
                    None,
                    calls=[
                        {
                            "id": "calendar-check",
                            "type": "function",
                            "function": {
                                "name": "benchmark_date_interval",
                                "arguments": json.dumps(
                                    {
                                        "start_source_id": rows[0]["source_id"],
                                        "start_date": "2025-01-20",
                                        "end_source_id": rows[-1]["source_id"],
                                        "end_date": "2025-02-03",
                                    }
                                ),
                            },
                        }
                    ],
                    finish="tool_calls",
                )
            assert any(
                message["role"] == "tool" and '"days": 14' in message["content"]
                for message in payload["messages"]
            )
            return completion("14 days")

    answer, result = execute_in_instance(
        instance,
        settings,
        {"answer": Scripted()},
        {},
        source_rows(instance),
        application=True,
    )
    assert answer == "14 days" and result["status"] == "COMPLETED"
    assert result["application"]["retained"]
    assert result["application"]["context_memory_ids"]


def test_checkpoint_comparison_rejects_changed_harness_and_counts_invalid_outputs():
    from scripts._checkpoint_evaluation import compare_reports
    from scripts._experiment_contracts import ComparisonPlan

    judge = {"model": "judge-fixture"}
    common = {
        "dataset_sha256": "corpus",
        "question_ids": ["q1", "q2"],
        "effective_retrieval_policy": {},
        "prompt_sha256": "prompt",
        "response_adapter": "strict-native-v2",
        "modes": ["direct"],
        "top_k": 20,
        "neighbors": 1,
        "preprocessing_version": "v2",
        "code": {"source_tree_sha256": "same"},
        "scope": "backend",
    }
    base = {
        "manifest": {**common, "config": {"answer": {"model": "base"}, "judge": judge}},
        "questions_detail": [
            {
                "question_id": qid,
                "mode": "direct",
                "status": "graded",
                "correct": True,
                "prediction": "answer",
            }
            for qid in common["question_ids"]
        ],
    }
    candidate = copy.deepcopy(base)
    candidate["manifest"]["config"]["answer"]["model"] = "trained"
    candidate["questions_detail"][1] = {
        "question_id": "q2",
        "mode": "direct",
        "status": "invalid_final",
    }
    plan = ComparisonPlan(
        base_model="base",
        checkpoint_model="trained",
        dataset_sha256="corpus",
        question_ids=["q1", "q2"],
        effective_policy_sha256=digest({}),
        answer_prompt_sha256="prompt",
        response_adapter="strict-native-v2",
        judge_route_sha256=digest(judge),
    )
    result = compare_reports(base, candidate, plan)
    assert result["checkpoint"]["success_per_planned"] == 0.5
    assert result["checkpoint"]["invalid_final_rate"] == 0.5
    assert not result["eligible_for_promotion_review"]
    assert result["checkpoint"]["wilson_95_success_interval"]
    candidate["manifest"]["neighbors"] = 2
    with pytest.raises(ValueError, match="implementation"):
        compare_reports(base, candidate, plan)


def test_full_paid_protocol_gate_requires_frozen_heldout_report(tmp_path, instance):
    from scripts.experiment_pipeline import validate_protocol_gate

    plan = evaluation_plan()
    with pytest.raises(ValueError, match="held-out"):
        validate_protocol_gate(plan)
    rows = [{**instance, "question_id": f"synthetic_new_{i}"} for i in range(60)]
    data = tmp_path / "data.json"
    atomic_json(data, rows)
    heldout, _ = select_instances(rows, 60, split="heldout")
    selected = heldout[:6]
    report = {
        "manifest": {
            "split": "heldout",
            "execution": "live",
            "dataset_profile": "synthetic",
            "dataset_sha256": digest(rows),
            "code": {"source_tree_sha256": "fixture"},
            "config": {},
            "modes": ["direct"],
        },
        "completion_rate": 1,
        "questions_detail": [
            {"question_id": row["question_id"], "mode": "direct", "status": "graded"}
            for row in selected
        ],
    }
    path = tmp_path / "report.json"
    atomic_json(path, report)
    plan = plan.model_copy(
        update={
            "dataset_path": str(data),
            "dataset_sha256": digest(rows),
            "profile_sha256": digest({}),
            "validation_report_path": str(path),
            "validation_report_sha256": digest(report),
            "question_ids": [row["question_id"] for row in rows],
        }
    )
    validate_protocol_gate(plan)
    report["completion_rate"] = 0.5
    atomic_json(path, report)
    with pytest.raises(ValueError, match="changed"):
        validate_protocol_gate(plan)
    plan = plan.model_copy(update={"validation_report_sha256": digest(report)})
    with pytest.raises(ValueError, match="gate failed"):
        validate_protocol_gate(plan)
