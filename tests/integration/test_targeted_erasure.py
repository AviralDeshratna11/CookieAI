from uuid import uuid4

import pytest
from sqlalchemy import select

from database import operations_tables as o
from memory.schemas import MemoryCreate
from memory.security.auth import AccessDenied
from workers.queue import JobQueue


def test_erasure_cancels_referenced_job_and_preserves_unrelated_payload(
    service, ctx, engine
):
    first = service.create(ctx, MemoryCreate(text="Private source A"))
    other_ctx = ctx.model_copy(update={"session_id": uuid4()})
    second = service.create(other_ctx, MemoryCreate(text="Unrelated source B"))
    queue = JobQueue(engine)
    affected = queue.enqueue(
        ctx, "memory.graph", {"memory_id": str(first.memory_id)}, "a", priority=1
    )
    preserved = queue.enqueue(
        other_ctx, "memory.graph", {"memory_id": str(second.memory_id)}, "b"
    )
    claimed = queue.claim()
    assert claimed["id"] == affected
    service.delete(ctx, first.memory_id)
    execution = ctx.model_copy(
        update={
            "execution_job_id": claimed["id"],
            "execution_lease_token": claimed["lease_token"],
        }
    )
    with pytest.raises(AccessDenied, match="canceled"):
        service.create(execution, MemoryCreate(text="Must not restore A"))
    queue.finish(claimed)
    with engine.connect() as db:
        rows = {r["id"]: r for r in db.execute(select(o.jobs)).mappings()}
        assert rows[affected]["status"] == "CANCELLED"
        assert rows[affected]["payload"] == {}
        assert rows[preserved]["status"] == "PENDING"
        assert rows[preserved]["payload"]["input"]["memory_id"] == str(second.memory_id)
    assert service.delete(ctx, first.memory_id) == set()


def test_raw_job_session_erasure_and_pending_namespace_read_are_scoped(
    service, ctx, engine
):
    first = service.create(ctx, MemoryCreate(text="Sensitive source"))
    queue = JobQueue(engine)
    raw = queue.enqueue(
        ctx,
        "memory.extract",
        {"messages": [{"role": "user", "content": "Sensitive source"}]},
        "raw",
    )
    later_ctx = ctx.model_copy(update={"session_id": uuid4()})
    independent = queue.enqueue(
        later_ctx,
        "memory.extract",
        {"messages": [{"role": "user", "content": "Unrelated input"}]},
        "independent",
    )
    namespace = queue.enqueue(ctx, "memory.reflect", {}, "snapshot-reader")
    service.delete(ctx, first.memory_id)
    with engine.connect() as db:
        rows = {r["id"]: r for r in db.execute(select(o.jobs)).mappings()}
        assert rows[raw]["payload"] == {}
        assert rows[namespace]["status"] == "CANCELLED"
        assert rows[independent]["status"] == "PENDING"
        assert "Sensitive source" not in str(list(rows.values()))
