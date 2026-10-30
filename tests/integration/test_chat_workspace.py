import hashlib
import json
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from memory.agent.service import AgentService, TurnInput
from memory.schemas import MemoryCreate
from memory.security.auth import Authenticator, Credential
from models.providers import Provider
from workers.runtime import Worker


def test_chat_uses_independent_nemotron_route_and_cross_session_context(
    service, ctx, monkeypatch
):
    source = service.create(ctx, MemoryCreate(text="Project Cedar uses PostgreSQL"))
    fresh = ctx.model_copy(update={"session_id": uuid4()})
    service.settings.assistant_model = "nvidia/Nemotron-3_5-Lightning"
    service.settings.assistant_completion_limit_parameter = "max_completion_tokens"
    service.settings.assistant_reasoning_effort = "none"
    calls = []

    def generate(self, endpoint, payload):
        calls.append(payload)
        assert payload["model"] == "nvidia/Nemotron-3_5-Lightning"
        assert payload["reasoning_effort"] == "none"
        assert "max_completion_tokens" in payload and "max_tokens" not in payload
        assert '"cross_session_retrieval": true' in payload["messages"][0]["content"]
        assert '"external_action_execution": false' in payload["messages"][0]["content"]
        assert "You are CookieAI" in payload["messages"][0]["content"]
        package = json.loads(payload["messages"][1]["content"])[
            "untrusted_memory_context"
        ]
        assert package["current_session_id"] == str(fresh.session_id)
        assert any(
            item["session_id"] == str(ctx.session_id)
            for item in package["related_sessions"]
        )
        assert "PostgreSQL" in payload["messages"][1]["content"]
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Cedar uses PostgreSQL."},
                }
            ]
        }

    monkeypatch.setattr(Provider, "post", generate)
    agent = AgentService(service)
    turn = agent.submit(
        fresh,
        TurnInput(
            message="What database does Project Cedar use?",
            idempotency_key="workspace-new-session",
            mode="raw",
        ),
    )
    Worker(service).run_once()
    result = agent.get(fresh, UUID(turn["turn_id"]))
    assert result["status"] == "COMPLETED"
    assert result["pipeline"]["model"] == service.settings.assistant_model
    assert result["pipeline"]["session_id"] == str(fresh.session_id)
    assert result["pipeline"]["capabilities"]["cross_session_retrieval"] is True
    assert str(source.memory_id) in result["context_memory_ids"]
    assert len(calls) == 1  # Correlation does not make a duplicate LLM call.


def test_portal_config_exposes_effective_model_without_credentials(service, ctx):
    token = "workspace-test-token"
    auth = Authenticator(
        [
            Credential(
                hashlib.sha256(token.encode()).hexdigest(),
                ctx.user_id,
                ctx.requesting_agent_id,
                ctx.namespace_id,
            )
        ]
    )
    service.settings.assistant_model = "nvidia/Nemotron-3_5-Lightning"
    client = TestClient(create_app(service=service, auth=auth))
    assert client.get("/v1/portal/config").status_code == 401
    response = client.get(
        "/v1/portal/config",
        headers={
            "Authorization": "Bearer " + token,
            "X-Session-ID": str(ctx.session_id),
            "X-Purpose": "test",
        },
    )
    data = response.json()
    assert data["model"] == service.settings.assistant_model
    assert data["correlation_backend"] == "heuristic"
    assert "api_key" not in response.text and "provider_api_key" not in response.text


def test_assistant_rejects_truncated_or_reasoning_only_final(service):
    import pytest

    class InvalidGenerator:
        def __init__(self, content, finish):
            self.content, self.finish = content, finish

        def post(self, endpoint, payload):
            return {
                "choices": [
                    {"finish_reason": self.finish, "message": {"content": self.content}}
                ]
            }

    for content, finish in [
        ("partial answer", "length"),
        ("reasoning</think> answer", "stop"),
        (None, "stop"),
    ]:
        agent = AgentService(service, generator=InvalidGenerator(content, finish))
        with pytest.raises(ValueError):
            agent.generate(TurnInput(message="Test", idempotency_key="fixture"), {})


def test_assistant_provider_route_does_not_inherit_other_credentials(service):
    from pydantic import SecretStr

    service.settings.provider_api_key = SecretStr("different-provider-secret")
    service.settings.provider_enable_thinking = True
    service.settings.assistant_provider_base_url = (
        "https://api.tokenfactory.nebius.com/v1"
    )
    agent = AgentService(service)
    assert agent.generator.base_url == service.settings.assistant_provider_base_url
    assert agent.generator.api_key.get_secret_value() == ""
    assert agent.generator.settings.provider_enable_thinking is None
    service.settings.assistant_provider_api_key = SecretStr("private-fixture-key")
    assert (
        AgentService(service).generator.api_key.get_secret_value()
        == "private-fixture-key"
    )
    assert (
        service.settings.provider_api_key.get_secret_value()
        == "different-provider-secret"
    )
