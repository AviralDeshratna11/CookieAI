from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from database import cognitive_tables as c
from database import operations_tables as o
from database import tables as t
from memory.agent.service import AgentService, TurnFeedback, TurnInput
from memory.schemas import MemoryCreate, utcnow
from memory.security.auth import AccessDenied, Conflict
from models.providers import Provider
from workers.runtime import Worker


def test_durable_turn_recalls_and_records_only_user_as_independent_memory(
    service, ctx, engine, monkeypatch
):
    source = service.create(ctx, MemoryCreate(text="Project Maple uses PostgreSQL"))
    calls = []

    def post(self, endpoint, payload):
        calls.append(payload)
        assert "PostgreSQL" in payload["messages"][1]["content"]
        return {
            "choices": [
                {
                    "message": {
                        "content": "Project Maple uses PostgreSQL, according to your stored statement."
                    }
                }
            ]
        }

    monkeypatch.setattr(Provider, "post", post)
    agent = AgentService(service)
    fresh = ctx.model_copy(update={"session_id": uuid4()})
    body = TurnInput(
        message="What database does Maple use?",
        idempotency_key="first-turn",
        mode="raw",
    )
    submitted = agent.submit(fresh, body)
    assert agent.submit(fresh, body)["turn_id"] == submitted["turn_id"]
    assert Worker(service).run_once()
    result = agent.get(fresh, UUID(submitted["turn_id"]))
    assert result["status"] == "COMPLETED"
    assert str(source.memory_id) in result["context_memory_ids"]
    assert len(calls) == 1
    agent.process(fresh, UUID(submitted["turn_id"]))
    assert len(calls) == 1
    with engine.connect() as db:
        memories = db.execute(select(t.memories.c.payload)).scalars().all()
        assert not any(m["text"] == result["answer"] for m in memories)
        assert (
            db.execute(select(func.count()).select_from(t.messages)).scalar_one() == 2
        )
    feedback = TurnFeedback(feedback_id=uuid4(), helpful_memory_ids=[source.memory_id])
    receipt = agent.feedback(fresh, UUID(submitted["turn_id"]), feedback)
    assert agent.feedback(fresh, UUID(submitted["turn_id"]), feedback) == receipt
    current = service.get(ctx, source.memory_id)
    assert current.successful_use_count == 1
    assert current.truth_confidence == source.truth_confidence
    with pytest.raises(Conflict):
        agent.submit(fresh, body.model_copy(update={"message": "Different input"}))


def test_deletion_during_generation_prevents_cached_answer_or_ingestion(
    service, ctx, engine, monkeypatch
):
    source = service.create(
        ctx, MemoryCreate(text="Private Maple secret", privacy_class="PRIVATE")
    )

    def post(self, endpoint, payload):
        service.delete(ctx, source.memory_id)
        return {
            "choices": [
                {"message": {"content": "Must not retain the erased private secret"}}
            ]
        }

    monkeypatch.setattr(Provider, "post", post)
    agent = AgentService(service)
    submitted = agent.submit(
        ctx,
        TurnInput(
            message="Recall Maple secret", idempotency_key="erase-race", mode="raw"
        ),
    )
    Worker(service).run_once()
    result = agent.get(ctx, UUID(submitted["turn_id"]))
    assert result["status"] == "CANCELLED"
    assert result["answer"] is None
    with engine.connect() as db:
        row = db.execute(select(c.turns)).mappings().one()
        assert row["payload"] == {} and row["response"] is None
    with pytest.raises(AccessDenied):
        agent.get(
            ctx.model_copy(update={"requesting_agent_id": uuid4()}),
            UUID(submitted["turn_id"]),
        )


def test_provider_failure_then_worker_restart_preserves_observation(
    service, ctx, engine, monkeypatch
):
    attempts = []

    def post(self, endpoint, payload):
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError("synthetic provider interruption")
        return {"choices": [{"message": {"content": "Stored after recovery."}}]}

    monkeypatch.setattr(Provider, "post", post)
    agent = AgentService(service)
    submitted = agent.submit(
        ctx,
        TurnInput(
            message="Remember the synthetic recovery observation",
            mode="raw",
            idempotency_key="recovery",
        ),
    )
    Worker(service).run_once()
    pending = agent.get(ctx, UUID(submitted["turn_id"]))
    assert pending["status"] == "PENDING" and pending["job_status"] == "PENDING"
    assert pending["failure_class"] == "TimeoutError"
    with engine.begin() as db:
        db.execute(
            update(o.jobs)
            .where(o.jobs.c.id == UUID(submitted["job_id"]))
            .values(available_at=utcnow())
        )
    Worker(service).run_once()
    done = agent.get(ctx, UUID(submitted["turn_id"]))
    assert done["status"] == "COMPLETED" and len(done["memory_ids"]) == 1
    assert len(attempts) == 2
    assert (
        agent.submit(
            ctx,
            TurnInput(
                message="Remember the synthetic recovery observation",
                mode="raw",
                idempotency_key="recovery",
            ),
        )["turn_id"]
        == submitted["turn_id"]
    )
