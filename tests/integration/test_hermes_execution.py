import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from database import cognitive_tables as c
from memory.agent.backends import ExecutionResult
from memory.agent.hermes import HermesBackend
from memory.agent.service import AgentService, TurnInput
from memory.config import Settings
from memory.schemas import utcnow
from memory.security.auth import AccessDenied


def enable(service, ctx):
    service.settings.hermes_enabled = True
    service.settings.hermes_allowed_agents = [str(ctx.requesting_agent_id)]
    service.settings.hermes_python = Path("unused-test-runtime")
    service.settings.hermes_source = Path("unused-test-source")


def test_execution_crash_is_never_replayed(service, ctx, engine, monkeypatch):
    enable(service, ctx)
    agent = AgentService(service)
    turn = agent.submit(
        ctx,
        TurnInput(
            message="bounded pilot",
            backend="hermes",
            mode="raw",
            idempotency_key="crash",
        ),
    )
    identity = UUID(turn["turn_id"])
    calls = []

    def crash(self, *args):
        calls.append(1)
        now = utcnow().isoformat()
        self.on_observation(
            {
                "event_id": str(uuid4()),
                "sequence": 0,
                "tool": "cookieai_calculate",
                "success": True,
                "error_class": None,
                "started_at": now,
                "ended_at": now,
                "phase": "FINISHED",
            }
        )
        raise TimeoutError("simulated lost runtime")

    monkeypatch.setattr(HermesBackend, "run", crash)
    with pytest.raises(TimeoutError):
        agent.process(ctx, identity)
    result = agent.process(ctx, identity)
    assert result["execution"]["status"] == "UNKNOWN"
    assert len(result["execution"]["observations"]) == 1
    assert result["execution_episode_id"]
    assert len(calls) == 1
    assert agent.process(ctx, identity) == result


def test_execution_observations_recorded_once_without_claiming_task_success(
    service, ctx, monkeypatch
):
    enable(service, ctx)
    now = utcnow().isoformat()

    def run(self, identity, message, context):
        self.guard()
        return ExecutionResult(
            backend="hermes",
            run_id=identity,
            status="COMPLETED",
            answer="Observed result: 4",
            observations=[
                {
                    "event_id": str(uuid4()),
                    "sequence": 0,
                    "tool": "cookieai_calculate",
                    "success": True,
                    "error_class": None,
                    "started_at": now,
                    "ended_at": now,
                }
            ],
        )

    monkeypatch.setattr(HermesBackend, "run", run)
    agent = AgentService(service)
    turn = agent.submit(
        ctx,
        TurnInput(
            message="Calculate 2+2",
            backend="hermes",
            mode="raw",
            idempotency_key="calc",
        ),
    )
    identity = UUID(turn["turn_id"])
    result = agent.process(ctx, identity)
    assert result["execution"]["task_success"] is None
    assert result["execution_episode_id"]
    assert agent.process(ctx, identity) == result


def test_cancellation_fences_runtime_and_scrubs_turn(service, ctx, engine, monkeypatch):
    enable(service, ctx)
    agent = AgentService(service)
    turn = agent.submit(
        ctx,
        TurnInput(
            message="private pilot",
            backend="hermes",
            mode="raw",
            idempotency_key="cancel",
        ),
    )
    identity = UUID(turn["turn_id"])

    def run(self, *args):
        agent.cancel(ctx, identity)
        self.guard()

    monkeypatch.setattr(HermesBackend, "run", run)
    with pytest.raises(AccessDenied):
        agent.process(ctx, identity)
    with engine.connect() as db:
        row = db.execute(select(c.turns)).mappings().one()
        assert row["payload"] == {} and row["response"] is None
    assert agent.get(ctx, identity)["status"] == "CANCELLED"


def test_legacy_turn_hash_still_replays(service, ctx, engine):
    agent = AgentService(service)
    body = TurnInput(message="legacy request", idempotency_key="legacy")
    turn = agent.submit(ctx, body)
    with engine.connect() as db:
        assert "backend" not in db.execute(select(c.turns.c.payload)).scalar_one()
    assert agent.submit(ctx, body)["turn_id"] == turn["turn_id"]


def test_erasure_during_hermes_run_fences_late_events(service, ctx, monkeypatch):
    from memory.schemas import MemoryCreate

    enable(service, ctx)
    memory = service.create(ctx, MemoryCreate(text="Sensitive pilot dependency"))
    agent = AgentService(service)
    turn = agent.submit(
        ctx,
        TurnInput(
            message="Sensitive pilot dependency",
            backend="hermes",
            mode="raw",
            idempotency_key="erase",
        ),
    )
    identity = UUID(turn["turn_id"])

    def run(self, *args):
        service.delete(ctx, memory.memory_id)
        self.guard()

    monkeypatch.setattr(HermesBackend, "run", run)
    with pytest.raises(AccessDenied):
        agent.process(ctx, identity)
    assert agent.get(ctx, identity) == {
        "turn_id": str(identity),
        "status": "CANCELLED",
        "answer": None,
    }


@pytest.mark.skipif(
    not os.getenv("COOKIEAI_HERMES_PYTHON"),
    reason="isolated Hermes runtime not selected",
)
def test_real_pinned_hermes_loop_with_scripted_provider(tmp_path, monkeypatch):
    import subprocess

    homes = []
    launch = subprocess.Popen

    def capture(*args, **kwargs):
        homes.append(Path(kwargs["cwd"]))
        assert not any(key.endswith("API_KEY") for key in kwargs["env"])
        return launch(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", capture)
    # Real Hermes engine and SDK transport, deterministic model responses; no live LLM.
    settings = Settings(
        _env_file=None,
        hermes_python=Path(os.environ["COOKIEAI_HERMES_PYTHON"]),
        hermes_source=Path(os.environ["COOKIEAI_HERMES_SOURCE"]),
        hermes_timeout_seconds=60,
        assistant_prompt_tokens=32768,
    )

    class ScriptedProvider:
        calls = 0

        def post(self, endpoint, payload):
            self.calls += 1
            # During the real run no retained transcript may contain the prompt.
            for home in homes:
                retained = [
                    str(path.relative_to(home))
                    for path in home.rglob("*")
                    if path.is_file()
                    and b"Synthetic arithmetic recovery fixture" in path.read_bytes()
                ]
                assert not retained, retained
            if self.calls == 1:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "attempt-1",
                            "type": "function",
                            "function": {
                                "name": "cookieai_calculate",
                                "arguments": '{"expression":"1 / 0"}',
                            },
                        }
                    ],
                }
            elif self.calls == 2:
                assert "DivisionByZero" in str(payload["messages"])
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "attempt-2",
                            "type": "function",
                            "function": {
                                "name": "cookieai_calculate",
                                "arguments": '{"expression":"(0.1 + 0.2) * 10"}',
                            },
                        }
                    ],
                }
            else:
                assert "3.0" in str(payload["messages"])
                message = {
                    "role": "assistant",
                    "content": "The checked arithmetic result is 3.0.",
                }
            return {
                "id": "scripted",
                "object": "chat.completion",
                "created": 0,
                "model": settings.extraction_model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls"
                        if message.get("tool_calls")
                        else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }

    result = HermesBackend(
        settings, workspace=tmp_path, provider=ScriptedProvider()
    ).run(uuid4(), "Synthetic arithmetic recovery fixture", {})
    assert result.status == "COMPLETED", result
    assert [item["success"] for item in result.observations] == [False, True]
    assert result.usage["model_calls"] == 3
    assert result.task_success is None
    assert homes and all(not home.exists() for home in homes)


@pytest.mark.skipif(
    not os.getenv("COOKIEAI_HERMES_PYTHON"),
    reason="isolated Hermes runtime not selected",
)
def test_real_engine_durable_learning_and_later_context(service, ctx, monkeypatch):
    """Three separate synthetic executions, explicit outcomes, reuse and counterevidence.

    Model responses are scripted; this verifies the integration mechanics rather
    than representative model generalization or statistically independent data.
    """
    from memory.agent.service import TurnFeedback
    from memory.episodes.service import EpisodeInput, EpisodeService
    from memory.experiences.service import ExperienceService
    from memory.procedures.service import (
        ProcedureCompile,
        ProcedureFeedback,
        ProcedureService,
    )
    from memory.schemas import MemoryCreate
    from models.providers import Provider

    enable(service, ctx)
    service.settings.hermes_python = Path(os.environ["COOKIEAI_HERMES_PYTHON"])
    service.settings.hermes_source = Path(os.environ["COOKIEAI_HERMES_SOURCE"])
    seen_procedure = []

    def post(self, endpoint, payload):
        history = [row for row in payload["messages"] if row.get("role") == "tool"]
        seen_procedure.append(
            "cookieai_calculate" in str(payload["messages"])
            and "procedure_id" in str(payload["messages"])
        )
        if not history:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "failed-attempt",
                        "type": "function",
                        "function": {
                            "name": "cookieai_calculate",
                            "arguments": '{"expression":"1/0"}',
                        },
                    }
                ],
            }
        elif len(history) == 1:
            assert "DivisionByZero" in history[-1]["content"]
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "recovery-attempt",
                        "type": "function",
                        "function": {
                            "name": "cookieai_calculate",
                            "arguments": '{"expression":"2+2"}',
                        },
                    }
                ],
            }
        else:
            assert '"4"' in history[-1]["content"]
            message = {"role": "assistant", "content": "The checked result is 4."}
        return {
            "id": "synthetic-learning",
            "object": "chat.completion",
            "created": 0,
            "model": self.settings.extraction_model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls"
                    if message.get("tool_calls")
                    else "stop",
                }
            ],
        }

    monkeypatch.setattr(Provider, "post", post)
    agent = AgentService(service)
    episodes = []
    signature = {
        "goal_type": "evaluate_expression",
        "domain": "synthetic_arithmetic",
        "error_category": "division_by_zero",
        "environment": "isolated_fixture",
        "workflow_stage": "calculation",
    }
    for index in range(3):
        session = ctx.model_copy(update={"session_id": uuid4()})
        turn = agent.submit(
            session,
            TurnInput(
                message="Synthetic pilot arithmetic recovery",
                backend="hermes",
                mode="raw",
                idempotency_key=f"synthetic-learning-{index}",
                context_signature=signature,
            ),
        )
        identity = UUID(turn["turn_id"])
        result = agent.process(session, identity)
        assert result["execution"]["status"] == "COMPLETED"
        assert [item["success"] for item in result["execution"]["observations"]] == [
            False,
            True,
        ]
        recorded = EpisodeService(service).get(
            session, UUID(result["execution_episode_id"])
        )
        # Explicit fixture evaluator checks the actual tool result in post().
        confirmed = EpisodeInput(
            **recorded.model_dump(exclude={"episode_id", "confidence", "created_at"})
        )
        confirmed = confirmed.model_copy(
            update={"event_id": uuid4(), "outcome": "success"}
        )
        receipt = agent.feedback(
            session, identity, TurnFeedback(feedback_id=uuid4(), episode=confirmed)
        )
        episodes.append(UUID(receipt["episode_id"]))
    experience = ExperienceService(service).compile(ctx, episodes)
    procedures = ProcedureService(service)
    procedure = procedures.compile(
        ctx, ProcedureCompile(experience_ids=[experience.experience_id])
    )
    later = ctx.model_copy(update={"session_id": uuid4()})
    turn = agent.submit(
        later,
        TurnInput(
            message="Synthetic pilot arithmetic recovery",
            backend="hermes",
            mode="raw",
            idempotency_key="synthetic-reuse",
            context_signature=signature,
        ),
    )
    result = agent.process(later, UUID(turn["turn_id"]))
    assert str(procedure.procedure_id) in result["context_memory_ids"]
    assert any(seen_procedure)
    counterexample = service.create(
        ctx,
        MemoryCreate(
            text="Synthetic changed inputs: this recovery no longer meets the task goal",
            epistemic_type="OBSERVED",
        ),
    )
    revised = procedures.feedback(
        ctx,
        procedure.procedure_id,
        ProcedureFeedback(success=False, evidence_memory_id=counterexample.memory_id),
    )
    assert revised.confidence < procedure.confidence
