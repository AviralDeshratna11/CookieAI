from datetime import timedelta

import httpx
from sqlalchemy import select, update

from database import operations_tables as o
from memory.schemas import utcnow
from workers.queue import JobQueue


def test_aged_discovery_is_not_starved_by_fresh_chat(engine, ctx):
    queue = JobQueue(engine)
    discovery = queue.enqueue(ctx, "memory.reflect", {}, "old-discovery", priority=5)
    with engine.begin() as db:
        db.execute(
            update(o.jobs)
            .where(o.jobs.c.id == discovery)
            .values(created_at=utcnow() - timedelta(minutes=11))
        )
    queue.enqueue(
        ctx, "memory.agent_turn", {"turn_id": "fresh"}, "new-chat", priority=0
    )
    assert queue.claim()["id"] == discovery


def test_quota_backoff_reclaim_and_old_lease_cannot_finish(engine, ctx):
    queue = JobQueue(engine)
    identity = queue.enqueue(ctx, "memory.reflect", {}, "recovery")
    first = queue.claim()
    # Simulate process loss, including expiration of its renewable lease.
    with engine.begin() as db:
        db.execute(
            update(o.jobs)
            .where(o.jobs.c.id == identity)
            .values(lease_until=utcnow() - timedelta(seconds=1))
        )
    restarted = JobQueue(engine)
    second = restarted.claim()
    assert second["id"] == identity and second["lease_token"] != first["lease_token"]
    queue.finish(first)
    with engine.connect() as db:
        assert db.execute(select(o.jobs.c.status)).scalar_one() == "RUNNING"
    response = httpx.Response(
        429,
        headers={"Retry-After": "600"},
        request=httpx.Request("POST", "https://example.invalid"),
    )
    error = httpx.HTTPStatusError("quota", request=response.request, response=response)
    restarted.finish(second, error)
    with engine.connect() as db:
        row = db.execute(select(o.jobs)).mappings().one()
        assert row["status"] == "PENDING" and row["last_error"] == "ProviderRateLimited"
        assert row["available_at"].replace(
            tzinfo=utcnow().tzinfo
        ) > utcnow() + timedelta(seconds=590)
    assert restarted.claim() is None
    for attempt in range(4):
        with engine.begin() as db:
            db.execute(
                update(o.jobs)
                .where(o.jobs.c.id == identity)
                .values(available_at=utcnow() - timedelta(seconds=1))
            )
        restarted.finish(restarted.claim(), error)
    with engine.connect() as db:
        row = db.execute(select(o.jobs)).mappings().one()
        assert row["status"] == "FAILED" and row["retry_count"] == 5
        assert row["payload"]["context"]["namespace_id"] == str(ctx.namespace_id)
