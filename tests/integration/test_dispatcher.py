import os

import pytest
from sqlalchemy import select

from database import operations_tables as o
from memory.schemas import MemoryCreate
from workers.dispatcher import EventDispatcher
from workers.events import OutboxPublisher, RedisEventBus
from workers.runtime import Worker


def test_redis_outbox_to_authorized_projection_worker(service, ctx, engine):
    url = os.environ.get("MEMORY_TEST_REDIS_URL")
    if not url:
        pytest.skip("set MEMORY_TEST_REDIS_URL")
    import redis

    connection = redis.Redis.from_url(url)
    dispatcher = EventDispatcher(connection, service, ctx)
    try:
        service.create(ctx, MemoryCreate(text="Event projection"))
        assert OutboxPublisher(engine, RedisEventBus(connection), ctx).flush() == 1
        assert dispatcher.dispatch() == 1
        assert Worker(service, ctx).run_once()
        with engine.connect() as db:
            assert db.execute(select(o.jobs.c.status)).scalar() == "DONE"
    finally:
        connection.delete(dispatcher.stream)
        connection.close()
