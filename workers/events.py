"""Transactional outbox -> event bus, with at-least-once publication."""

from typing import Protocol

from sqlalchemy import select, update

from database import tables as t
from memory.schemas import utcnow


class EventBus(Protocol):
    def publish(self, event: dict) -> None: ...


class RedisEventBus:
    def __init__(self, redis):
        self.redis = redis

    def publish(self, event):
        self.redis.xadd(
            "memory.events:" + str(event["namespace_id"]),
            {key: str(value) for key, value in event.items()},
            maxlen=10000,
            approximate=True,
        )


class OutboxPublisher:
    def __init__(self, engine, bus, context=None):
        self.engine, self.bus = engine, bus
        self.context = context

    def flush(self, limit=100):
        with self.engine.begin() as db:
            if self.context:
                from database.repositories.memory import SQLMemoryRepository

                SQLMemoryRepository(db, self.context)
            statement = (
                select(t.outbox)
                .where(t.outbox.c.delivered_at.is_(None))
                .order_by(t.outbox.c.created_at)
                .limit(limit)
            )
            if self.context:
                statement = statement.where(
                    t.outbox.c.namespace_id == self.context.namespace_id
                )
            if db.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            rows = list(db.execute(statement).mappings())
            for row in rows:
                # No private memory text is carried by events.
                self.bus.publish(
                    {
                        "event_id": row["id"],
                        "namespace_id": row["namespace_id"],
                        "object_id": row["object_id"],
                        "event_type": row["event_type"],
                        "correlation_id": row["correlation_id"],
                    }
                )
                db.execute(
                    update(t.outbox)
                    .where(t.outbox.c.id == row["id"])
                    .values(delivered_at=utcnow(), attempts=row["attempts"] + 1)
                )
            return len(rows)
