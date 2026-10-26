from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import insert

from database import cognitive_tables as c
from memory.retrieval.correlation import CorrelationService
from memory.schemas import MemoryCreate


def test_correlate_groups_hits_by_originating_session_not_session_token(service, ctx):
    service.create(ctx, MemoryCreate(text="Project Cedar uses PostgreSQL for storage"))
    other_session_ctx = ctx.model_copy(update={"session_id": uuid4()})
    service.create(
        other_session_ctx,
        MemoryCreate(text="Project Cedar migrated its PostgreSQL database last week"),
    )
    service.create(ctx, MemoryCreate(text="The cafeteria menu changed on Tuesday"))

    correlation = CorrelationService(service)
    result = correlation.correlate(ctx, "What does Project Cedar use for storage?")

    assert result["reasoning_mode"] == "heuristic"
    matched_sessions = {
        entry["session_id"]
        for entry in result["sessions"]
        if any("cedar" in memory["text"].lower() for memory in entry["memories"])
    }
    assert str(ctx.session_id) in matched_sessions
    assert str(other_session_ctx.session_id) in matched_sessions
    current = next(e for e in result["sessions"] if e["session_id"] == str(ctx.session_id))
    assert current["is_current_session"] is True
    assert any("cedar" in term for term in current["shared_terms"])


def test_conversations_lists_sessions_most_recent_first(service, ctx, engine):
    other_session_id = uuid4()
    with engine.begin() as db:
        db.execute(
            insert(c.turns).values(
                id=uuid4(),
                namespace_id=ctx.namespace_id,
                agent_id=ctx.requesting_agent_id,
                session_id=ctx.session_id,
                idempotency_key="k1",
                request_hash="h1",
                status="COMPLETED",
                payload={"message": "What does Cedar use?"},
                response=None,
                context_refs={},
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        db.execute(
            insert(c.turns).values(
                id=uuid4(),
                namespace_id=ctx.namespace_id,
                agent_id=ctx.requesting_agent_id,
                session_id=other_session_id,
                idempotency_key="k2",
                request_hash="h2",
                status="COMPLETED",
                payload={"message": "Second conversation"},
                response=None,
                context_refs={},
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        )

    conversations = CorrelationService(service).conversations(ctx)

    assert [item["session_id"] for item in conversations] == [
        str(other_session_id),
        str(ctx.session_id),
    ]
    assert conversations[0]["label"] == "Second conversation"
    assert conversations[1]["is_current_session"] is True


def test_turns_hydrates_a_past_conversation_by_session_id(service, ctx, engine):
    with engine.begin() as db:
        db.execute(
            insert(c.turns).values(
                id=uuid4(),
                namespace_id=ctx.namespace_id,
                agent_id=ctx.requesting_agent_id,
                session_id=ctx.session_id,
                idempotency_key="k1",
                request_hash="h1",
                status="COMPLETED",
                payload={"message": "What does Cedar use?"},
                response={"answer": "PostgreSQL."},
                context_refs={},
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )

    turns = CorrelationService(service).turns(ctx, ctx.session_id)

    assert len(turns) == 1
    assert turns[0]["message"] == "What does Cedar use?"
    assert turns[0]["answer"] == "PostgreSQL."
    assert turns[0]["status"] == "COMPLETED"
