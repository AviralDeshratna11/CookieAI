"""No hosted calls: mock HTTP plus the real pinned Hermes runtime when present."""

import copy
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from scripts._benchmark_runtime import (
    BudgetExceeded,
    CallLimitExceeded,
    InvalidCompletion,
    Ledger,
    MeteredProvider,
    final_content,
    isolated_settings,
    money_units,
)
from scripts._longmemeval_harness import (
    ROOT,
    CachedEmbedding,
    answer_messages,
    execute,
    pack_evidence,
    paired_results,
    parse_verdict,
    probe_tools,
    report,
    run_hermes,
    select_instances,
    source_rows,
    validate_config,
    validate_instances,
)


@pytest.fixture
def instances():
    return json.loads((ROOT / "tests/fixtures/longmemeval_synthetic.json").read_text())


@pytest.fixture
def route():
    # Synthetic mock rates, not a claim about any real model or current pricing.
    return {
        "base_url": "https://api.tokenfactory.nebius.com/v1",
        "api_key_env": "BENCHMARK_TEST_KEY",
        "model": "nvidia/synthetic-test-model",
        "bounded_output_verified": True,
        "pricing": {
            "input": "1",
            "output": "2",
            "currency": "USD",
            "unit": "per_million_tokens",
            "source_url": "https://nebius.com/synthetic-test-only",
            "verified_on": date.today().isoformat(),
            "output_includes_reasoning": True,
        },
    }


def completion(text="4", *, finish="stop", usage=True, calls=None):
    result = {
        "id": "synthetic",
        "object": "chat.completion",
        "created": 0,
        "model": "nvidia/synthetic-test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": text},
            }
        ],
    }
    if usage:
        result["usage"] = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
    if calls:
        result["choices"][0]["message"]["tool_calls"] = calls
    return result


def options(tmp_path, **kwargs):
    defaults = dict(
        data=str(ROOT / "tests/fixtures/longmemeval_synthetic.json"),
        limit=12,
        seed=42,
        heldout_fraction=0.2,
        split="development",
        profile=None,
        mode="retrieval-only",
        live=False,
        replay=False,
        dry_run=False,
        dataset_profile="synthetic",
        top_k=20,
        neighbors=1,
        artifact_root=str(tmp_path / "artifacts"),
        run_dir=str(tmp_path / "run"),
        max_cost_usd="1",
        max_calls=100,
        probe_tools=False,
    )
    return SimpleNamespace(**(defaults | kwargs))


def test_dataset_validation_rejects_silent_zip_and_duplicate_ids(instances):
    validate_instances(instances)
    wrong = copy.deepcopy(instances)
    wrong[0]["haystack_dates"].pop()
    with pytest.raises(ValueError, match="differ in length"):
        validate_instances(wrong)
    with pytest.raises(ValueError, match="Question IDs"):
        validate_instances(instances + instances)


def test_split_is_deterministic_disjoint_and_stratified(instances):
    rows = []
    for index in range(10):
        for row in instances:
            row = {**row, "question_id": f"{index}_{row['question_id']}"}
            rows.append(row)
    development, heldout = select_instances(rows, 100)
    test, same_heldout = select_instances(list(reversed(rows)), 100, split="heldout")
    assert heldout == same_heldout
    assert {row["question_id"] for row in development}.isdisjoint(heldout)
    assert {row["question_id"] for row in test} == set(heldout)
    assert {row["question_type"] for row in development} == {
        row["question_type"] for row in instances
    }


def test_offline_ignores_ambient_providers_and_never_networks(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_EMBEDDING_BACKEND", "compatible")
    monkeypatch.setenv("MEMORY_DATABASE_URL", "postgresql://never-use")
    monkeypatch.setenv("MEMORY_PROVIDER_BASE_URL", "https://never-use.invalid")

    def deny(*args, **kwargs):
        raise AssertionError("Offline path attempted HTTP")

    monkeypatch.setattr(httpx.Client, "send", deny)
    assert isolated_settings().embedding_backend == "hash-test"
    assert "never-use" not in isolated_settings().database_url
    result = execute(options(tmp_path))
    assert result["status_counts"] == {"retrieved": 4}
    assert result["cost"]["spent_or_reserved_usd"] == "0"
    for row in result["questions_detail"]:
        assert all(
            "session_date" in source and "role" in source for source in row["evidence"]
        )
    assert result["by_type"]["abstention"]["mean_session_recall"] is None


def test_source_content_order_dates_and_packing(instances):
    row = instances[0]
    sources = source_rows(row)
    sources.reverse()
    packed, trace = pack_evidence(
        sources, row["question"], row["question_date"], 12000, 32768, 512
    )
    assert packed[0]["session_id"] == "bike_order"
    assert packed[0]["turn_index"] == 0
    assert packed[1]["role"] == "assistant"
    assert packed[-1]["text"] == "My bicycle arrived today."
    payload = answer_messages(row["question"], row["question_date"], packed)
    assert "2025/02/10" in payload[1]["content"]
    assert "2025/01/20" in payload[1]["content"]
    assert not trace["truncated"]
    _, truncated = pack_evidence(
        sources, row["question"], row["question_date"], 1, 32768, 512
    )
    assert len(truncated["omitted_source_ids"]) == len(sources)


def test_gold_never_enters_answer_generation_and_judge_failure_resumes(
    tmp_path, instances, route, monkeypatch
):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    instances[0]["answer"] = "GOLD_SECRET"
    data = tmp_path / "data.json"
    data.write_text(json.dumps([instances[0]]))
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"answer": route, "judge": route}))
    calls = []

    def transport(request):
        payload = json.loads(request.content)
        calls.append(payload)
        text = str(payload["messages"])
        if "Correct Answer:" in text:
            assert "GOLD_SECRET" in text
            return httpx.Response(503)  # Saved answer survives.
        assert "GOLD_SECRET" not in text
        assert "question_type" not in text
        assert "answer_session_ids" not in text
        return httpx.Response(200, json=completion("14 days"))

    def factory(*args, **kwargs):
        return MeteredProvider(
            *args, **kwargs, transport=httpx.MockTransport(transport)
        )

    args = options(
        tmp_path, data=str(data), profile=str(profile), mode="direct", live=True
    )
    first = execute(args, provider_factory=factory)
    assert first["questions_detail"][0]["prediction"] == "14 days"
    assert first["questions_detail"][0]["failure_stage"] == "judge"
    calls.clear()

    def recover(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert "Correct Answer:" in str(payload["messages"])
        return httpx.Response(200, json=completion("yes"))

    def recovered(*args, **kwargs):
        return MeteredProvider(*args, **kwargs, transport=httpx.MockTransport(recover))

    second = execute(args, provider_factory=recovered)
    assert second["valid_grades"] == 1
    assert len(calls) == 1
    assert second["questions_detail"][0]["prediction"] == "14 days"


def test_ledger_serializes_concurrent_reservations_and_crash_restart(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = Ledger(path, "0.01", 10)
    barrier = threading.Barrier(2)

    def reserve(_):
        barrier.wait()
        try:
            return ledger.reserve("answer", "same", money_units("0.007"))
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sum(value is not None for value in results) == 1
    restarted = Ledger(path, "0.01", 10)
    assert restarted.summary()["spent_or_reserved_usd"] == "0.007"
    with pytest.raises(BudgetExceeded):
        restarted.reserve("answer", "other", money_units("0.004"))
    with pytest.raises(ValueError, match="increase"):
        Ledger(path, "0.02", 10)


def test_cached_replay_needs_no_key_or_network(tmp_path, route, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=completion())
    )
    provider = MeteredProvider(
        route, ledger, tmp_path / "cache", "answer", transport=transport
    )
    payload = {
        "model": route["model"],
        "max_tokens": 32,
        "messages": [{"role": "user", "content": "2+2"}],
    }
    assert final_content(provider.post("/chat/completions", payload)) == "4"
    monkeypatch.delenv("BENCHMARK_TEST_KEY")
    replay = MeteredProvider(route, ledger, tmp_path / "cache", "answer", replay=True)
    assert replay.post("/chat/completions", payload) == provider.post(
        "/chat/completions", payload
    )
    assert ledger.summary()["calls"] == 1
    with pytest.raises(FileNotFoundError):
        replay.post("/chat/completions", {**payload, "max_tokens": 33})


def test_embedding_batches_reused_by_memory_service_without_extra_ingestion_calls(
    instances, engine, ctx
):
    from memory.service import MemoryService
    from models.providers import HashEmbedding
    from scripts._longmemeval_harness import NoExtractor, ingest

    row = copy.deepcopy(instances[0])
    row["haystack_sessions"][0][0]["content"] += " I call this Project Atlas."
    rows = source_rows(row)
    calls = []

    class EmbeddingProvider:
        def post(self, endpoint, payload):
            calls.append(payload)
            assert isinstance(payload["input"], list)
            return {
                "data": [
                    {"index": index, "embedding": HashEmbedding(8).embed(text)}
                    for index, text in reversed(list(enumerate(payload["input"])))
                ]
            }

    settings = isolated_settings(
        embedding_model="synthetic-embedding", embedding_dimensions=8
    )
    embedder = CachedEmbedding(settings, EmbeddingProvider())
    embedder.prewarm(rows, 16)
    prewarm_calls = len(calls)
    assert prewarm_calls == 1
    service = MemoryService(engine, embedder, NoExtractor(), settings)
    mapping = ingest(service, ctx, rows)
    assert len(mapping) == len(rows)
    assert len(calls) == prewarm_calls


def test_overrun_keeps_response_and_blocks_further_spend(tmp_path, route, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    result = completion()
    result["usage"]["completion_tokens"] = 1_000_000
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    provider = MeteredProvider(
        route,
        ledger,
        tmp_path / "cache",
        "answer",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result)),
    )
    payload = {"model": route["model"], "max_tokens": 32, "messages": []}
    with pytest.raises(BudgetExceeded, match="exceeded"):
        provider.post("/chat/completions", payload)
    assert ledger.summary()["states"]["overrun"]["calls"] == 1
    # The unexpected response is retained for reconciliation, not paid for twice.
    assert provider.post("/chat/completions", payload) == result
    with pytest.raises(BudgetExceeded, match="reconcile"):
        provider.post("/chat/completions", {**payload, "max_tokens": 33})


@pytest.mark.parametrize(
    "status,expected", [(401, 1), (400, 1), (404, 1), (429, 2), (503, 2)]
)
def test_bounded_retries_keep_reservations(
    tmp_path, route, monkeypatch, status, expected
):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    route["attempts"] = 2
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    provider = MeteredProvider(
        route,
        ledger,
        tmp_path / "cache",
        "answer",
        sleep=lambda delay: None,
        transport=httpx.MockTransport(lambda request: httpx.Response(status)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        provider.post(
            "/chat/completions",
            {"model": route["model"], "max_tokens": 32, "messages": []},
        )
    assert ledger.summary()["calls"] == expected
    assert ledger.summary()["states"]["uncertain"]["calls"] == expected


def test_missing_usage_retains_reservation_and_stops_later_paid_calls(
    tmp_path, route, monkeypatch
):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    provider = MeteredProvider(
        route,
        ledger,
        tmp_path / "cache",
        "answer",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=completion(usage=False))
        ),
    )
    payload = {"model": route["model"], "max_tokens": 32, "messages": []}
    provider.post("/chat/completions", payload)
    assert ledger.summary()["states"]["missing_usage"]["calls"] == 1
    with pytest.raises(BudgetExceeded):
        provider.post("/chat/completions", {**payload, "max_tokens": 33})


def test_unaccounted_reasoning_usage_cannot_release_reservation(
    tmp_path, route, monkeypatch
):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    result = completion()
    result["usage"]["total_tokens"] = 115
    result["usage"]["completion_tokens_details"] = {"reasoning_tokens": 100}
    provider = MeteredProvider(
        route,
        ledger,
        tmp_path / "cache",
        "answer",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result)),
    )
    payload = {"model": route["model"], "max_tokens": 128, "messages": []}
    provider.post("/chat/completions", payload)
    assert ledger.summary()["states"]["missing_usage"]["calls"] == 1
    with pytest.raises(BudgetExceeded):
        provider.post("/chat/completions", {**payload, "max_tokens": 129})


def test_metered_transport_honors_remaining_hermes_deadline(
    tmp_path, route, monkeypatch
):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    ledger = Ledger(tmp_path / "ledger.sqlite3")

    def transport(request):
        assert 0 < request.extensions["timeout"]["read"] <= 0.5
        return httpx.Response(200, json=completion())

    provider = MeteredProvider(
        route,
        ledger,
        tmp_path / "cache",
        "answer",
        transport=httpx.MockTransport(transport),
    )
    provider.deadline = time.monotonic() + 0.5
    payload = {"model": route["model"], "max_tokens": 32, "messages": []}
    provider.post("/chat/completions", payload)
    provider.deadline = time.monotonic() - 1
    with pytest.raises(TimeoutError):
        provider.post("/chat/completions", {**payload, "max_tokens": 33})
    assert ledger.summary()["calls"] == 1


def test_per_question_request_allowance_includes_retries(tmp_path, route, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    route["attempts"] = 2
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    provider = MeteredProvider(
        route,
        ledger,
        tmp_path / "cache",
        "answer",
        sleep=lambda delay: None,
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    )
    provider.remaining_calls = 1
    with pytest.raises(CallLimitExceeded):
        provider.post(
            "/chat/completions",
            {"model": route["model"], "max_tokens": 32, "messages": []},
        )
    assert ledger.summary()["calls"] == 1


def test_nebius_completion_parameter_bounds_reasoning(tmp_path, route, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    route["completion_limit_parameter"] = "max_completion_tokens"
    route["reasoning_effort"] = "none"

    def transport(request):
        payload = json.loads(request.content)
        assert payload["max_completion_tokens"] == 128
        assert "max_tokens" not in payload
        assert payload["reasoning_effort"] == "none"
        return httpx.Response(200, json=completion())

    provider = MeteredProvider(
        route,
        Ledger(tmp_path / "ledger.sqlite3"),
        tmp_path / "cache",
        "answer",
        transport=httpx.MockTransport(transport),
    )
    provider.post(
        "/chat/completions",
        {"model": route["model"], "max_tokens": 128, "messages": []},
    )


def test_embedding_response_limit_is_explicitly_forwarded(tmp_path, route, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    route["model_response_bytes"] = 1048576
    from models.providers import Provider

    def post(self, endpoint, payload):
        assert self.settings.model_response_bytes == 1048576
        return {
            "data": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
        }

    monkeypatch.setattr(Provider, "post", post)
    provider = MeteredProvider(
        route, Ledger(tmp_path / "ledger.sqlite3"), tmp_path / "cache", "embedding"
    )
    provider.post("/embeddings", {"model": route["model"], "input": ["synthetic"]})


@pytest.mark.parametrize(
    "result",
    [
        completion("yes indeed"),
        completion("yesterday"),
        completion(None),
        completion("yes", finish="length"),
        completion("<think>yes</think>"),
    ],
)
def test_invalid_grade_is_never_accepted(result):
    with pytest.raises(InvalidCompletion):
        parse_verdict(result)


def test_metric_denominators_include_failures_and_invalid_grades():
    rows = [
        {
            "status": status,
            "correct": status == "graded",
            "question_id": str(i),
            "mode": "direct",
            "question_type": "multi-session",
            "abstention": False,
        }
        for i, status in enumerate(
            ["graded", "failed", "invalid_grade", "budget_skipped"]
        )
    ]
    summary = report(rows, {}, 4)
    assert summary["accuracy_among_valid_grades"] == 1
    assert summary["all_attempted_success_rate"] == pytest.approx(1 / 3)
    assert summary["grade_coverage"] == 0.25
    assert paired_results(rows)["valid_pairs"] == 0


def test_dry_run_placeholder_profile_and_incompatible_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(
        httpx.Client,
        "send",
        lambda *args, **kwargs: pytest.fail("No HTTP during dry run"),
    )
    args = options(
        tmp_path,
        dry_run=True,
        mode="compare",
        profile=str(ROOT / "config/benchmark.nebius.example.json"),
    )
    dry = execute(args)
    assert dry["dry_run"]["remote_requests"] == 0
    assert len(dry["dry_run"]["price_validation_blockers"]) == 2
    args.top_k = 3
    with pytest.raises(ValueError, match="Incompatible resume"):
        execute(args)
    with pytest.raises(ValueError, match="credentials"):
        validate_config({"answer": {"api_key": "never-log-me"}})


def test_tool_probe_round_trip_and_ids(route):
    class Scripted:
        def __init__(self):
            self.route, self.calls = route, []

        def post(self, endpoint, payload):
            self.calls.append(payload)
            if len(self.calls) == 1:
                return completion(
                    None,
                    finish="tool_calls",
                    calls=[
                        {
                            "id": "probe-tool-id",
                            "type": "function",
                            "function": {
                                "name": "cookieai_calculate",
                                "arguments": '{"expression":"2+2"}',
                            },
                        }
                    ],
                )
            assert payload["messages"][-1]["tool_call_id"] == "probe-tool-id"
            assert json.loads(payload["messages"][-1]["content"]) == {"value": "4"}
            return completion("4")

    provider = Scripted()
    probe_tools(provider, 128)
    assert len(provider.calls) == 2


def test_real_pinned_hermes_receives_evidence_and_uses_broker_arithmetic(
    tmp_path, instances
):
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
        pytest.skip(
            "Install the pinned isolated Hermes runtime to run this integration check"
        )
    settings = isolated_settings(
        hermes_python=python,
        hermes_source=source,
        hermes_max_iterations=4,
        hermes_timeout_seconds=60,
        extraction_model="nvidia/synthetic-test-model",
        assistant_output_tokens=512,
    )
    calls = []

    class Scripted:
        def post(self, endpoint, payload):
            calls.append(payload)
            text = str(payload["messages"])
            assert "2025/02/10" in text and "2025/01/20" in text
            assert "question_type" not in text and "answer_session_ids" not in text
            assert {tool["function"]["name"] for tool in payload["tools"]} == {
                "cookieai_calculate"
            }
            if len(calls) == 1:
                return completion(
                    None,
                    finish="tool_calls",
                    calls=[
                        {
                            "id": "arithmetic-id",
                            "type": "function",
                            "function": {
                                "name": "cookieai_calculate",
                                "arguments": '{"expression":"7*2"}',
                            },
                        }
                    ],
                )
            assert any(
                row["role"] == "tool" and "14" in row["content"]
                for row in payload["messages"]
            )
            return completion("14 days")

    question = instances[0]
    answer, execution = run_hermes(
        settings,
        Scripted(),
        question["question"],
        question["question_date"],
        source_rows(question),
        tmp_path,
    )
    assert answer == "14 days"
    assert execution["observations"][0]["success"]
    assert len(calls) == 2


def test_complete_paired_harness_with_real_engine_and_mock_http(
    tmp_path, instances, route, monkeypatch
):
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
        pytest.skip("Pinned runtime unavailable")
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "synthetic-only")
    data = tmp_path / "sample.json"
    data.write_text(json.dumps([instances[0]]))
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "answer": route,
                "judge": route,
                "hermes": {"python": str(python), "source": str(source)},
            }
        )
    )

    def transport(request):
        payload = json.loads(request.content)
        messages = payload["messages"]
        if messages[0]["content"].startswith("Call cookieai_calculate"):
            if messages[-1]["role"] == "tool":
                return httpx.Response(200, json=completion("4"))
            return httpx.Response(
                200,
                json=completion(
                    None,
                    finish="tool_calls",
                    calls=[
                        {
                            "id": "probe",
                            "type": "function",
                            "function": {
                                "name": "cookieai_calculate",
                                "arguments": '{"expression":"2+2"}',
                            },
                        }
                    ],
                ),
            )
        if "Correct Answer:" in str(messages):
            return httpx.Response(200, json=completion("yes"))
        assert "2025/02/10" in str(messages)
        assert "2025/01/20" in str(messages)
        return httpx.Response(200, json=completion("14 days"))

    def factory(*args, **kwargs):
        return MeteredProvider(
            *args, **kwargs, transport=httpx.MockTransport(transport)
        )

    result = execute(
        options(
            tmp_path,
            data=str(data),
            profile=str(profile),
            mode="compare",
            live=True,
            probe_tools=True,
        ),
        provider_factory=factory,
    )
    assert result["status_counts"] == {"graded": 2}
    direct, hermes = result["questions_detail"]
    assert direct["evidence"] == hermes["evidence"]
    assert result["paired"]["valid_pairs"] == 1
    assert result["paired"]["hermes_only_correct"] == 0
    assert hermes["execution"]["backend"] == "hermes"
    assert result["cost"]["calls"] == 5  # probe 2 + answer 2 + shared cached judge 1
    assert (tmp_path / "run/hypotheses.direct.json").exists()
    assert (tmp_path / "run/hypotheses.hermes.json").exists()
