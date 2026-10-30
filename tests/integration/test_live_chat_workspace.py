import json
from datetime import date
from uuid import UUID, uuid4

import httpx
import pytest

from memory.agent.service import AgentService, TurnInput
from scripts._benchmark_runtime import Ledger, MeteredProvider
from scripts.chat_workspace import build_workspace, open_budget
from workers.runtime import Worker


def test_live_workspace_routes_chat_and_semantic_embeddings_through_one_ledger(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TEST_CHAT_KEY", "mock-private-key")
    route = {
        "base_url": "https://api.tokenfactory.nebius.com/v1",
        "api_key_env": "TEST_CHAT_KEY",
        "model": "nvidia/fixture",
        "bounded_output_verified": True,
        "completion_limit_parameter": "max_completion_tokens",
        "pricing": {
            "input": "0.01",
            "output": "0.02",
            "currency": "USD",
            "unit": "per_million_tokens",
            "output_includes_reasoning": True,
            "verified_on": date.today().isoformat(),
            "source_url": "https://nebius.com/fixture",
        },
    }
    embedding_route = {**route, "model": "embedding-fixture"}
    profile = {
        "answer": {**route, "reasoning_effort": "none"},
        "embedding": {
            "backend": "compatible",
            "route": embedding_route,
            "dimensions": 8,
            "version": "1",
        },
    }
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [{"index": 0, "embedding": [1.0] * 8}],
                    "usage": {"prompt_tokens": 10, "total_tokens": 10},
                },
            )
        assert payload["model"] == "nvidia/fixture"
        assert "max_completion_tokens" in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "Connected."}}
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 3,
                    "total_tokens": 103,
                },
            },
        )

    ledger = Ledger(tmp_path / "budget.sqlite3", "0.1", 100)
    providers = {
        name: MeteredProvider(
            profile["answer"] if name == "answer" else embedding_route,
            ledger,
            tmp_path / "cache",
            name,
            transport=httpx.MockTransport(respond),
        )
        for name in ["answer", "embedding"]
    }
    app, memory, ctx = build_workspace(
        tmp_path / "workspace", ledger, profile, providers
    )
    session = ctx.model_copy(update={"session_id": uuid4()})
    try:
        agent = AgentService(memory)
        result = agent.submit(
            session,
            TurnInput(
                message="Remember that Cedar uses PostgreSQL.",
                idempotency_key="live-fixture",
                mode="raw",
            ),
        )
        Worker(memory, ctx).run_once()
        answer = agent.get(session, UUID(result["turn_id"]))
        assert answer["answer"] == "Connected." and answer["status"] == "COMPLETED"
        assert answer["pipeline"]["session_id"] == str(session.session_id)
        assert "/v1/embeddings" in calls and "/v1/chat/completions" in calls
        assert ledger.summary()["calls"] == len(calls)
        assert (tmp_path / "workspace/access-token.txt").exists()
    finally:
        memory.engine.dispose()


def test_live_budget_requires_existing_history_and_keeps_parent_policy(tmp_path):
    with pytest.raises(ValueError, match="existing authoritative"):
        open_budget(tmp_path / "budget.sqlite3")
    ledger = Ledger(tmp_path / "budget.sqlite3", "0.5", 100)
    request = ledger.reserve("fixture", "old", 1000)
    ledger.settle(request, 1000, {"fixture": True})
    chat, ceiling = open_budget(tmp_path / "budget.sqlite3", "0.1")
    assert chat.summary()["calls"] == 1
    assert chat.summary()["cap_usd"] == "0.5"
    assert ceiling == "0.100001"
    with pytest.raises(ValueError, match="at most"):
        open_budget(tmp_path / "budget.sqlite3", "5")


def test_workspace_budget_restart_cannot_reset_allowance(tmp_path):
    from scripts.chat_workspace import workspace_budget

    parent = Ledger(tmp_path / "budget.sqlite3", "0.5", 100)
    root = tmp_path / "workspace"
    first, ceiling = workspace_budget(root, parent.path, "0.1")
    identity = first.reserve("fixture", "used", 1000)
    first.settle(identity, 1000, {"fixture": True})
    restarted, same = workspace_budget(root, parent.path, "0.1")
    assert same == ceiling == "0.1"
    assert restarted.summary()["calls"] == 1
    with pytest.raises(ValueError, match="binding changed"):
        workspace_budget(root, parent.path, "0.2")
