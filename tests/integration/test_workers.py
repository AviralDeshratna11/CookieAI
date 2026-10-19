from sqlalchemy import select

from database import operations_tables as o
from memory.schemas import MemoryCreate
from workers.events import OutboxPublisher
from workers.queue import JobQueue
from workers.runtime import Worker


def test_durable_job_idempotency_and_execution(service, ctx, engine):
    queue = JobQueue(engine)
    first = queue.enqueue(ctx, "memory.reflect", {}, "reflection-job")
    assert queue.enqueue(ctx, "memory.reflect", {}, "reflection-job") == first
    assert Worker(service).run_once()
    assert not Worker(service).run_once()
    with engine.connect() as db:
        assert db.execute(select(o.jobs.c.status)).scalar() == "DONE"


def test_failed_job_retries_without_private_error_content(service, ctx, engine):
    queue = JobQueue(engine)
    queue.enqueue(ctx, "memory.extract", {"invalid": "private text"}, "bad-job")
    Worker(service).run_once()
    with engine.connect() as db:
        row = db.execute(select(o.jobs)).mappings().one()
        assert row["status"] == "PENDING"
        assert row["retry_count"] == 1
        assert "private" not in row["last_error"]


def test_outbox_publication_is_content_free_and_idempotent(service, ctx, engine):
    service.create(ctx, MemoryCreate(text="private source content"))

    class Bus:
        def __init__(self):
            self.events = []

        def publish(self, event):
            self.events.append(event)

    bus = Bus()
    publisher = OutboxPublisher(engine, bus)
    assert publisher.flush() == 1
    assert publisher.flush() == 0
    assert "private source content" not in str(bus.events)
