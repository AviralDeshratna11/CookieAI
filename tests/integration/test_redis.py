import os

import pytest

from memory.context.working import RedisWorkingMemory
from memory.schemas import MemoryCreate


def test_redis_working_references_do_not_resurrect_deleted_content(service, ctx):
    url = os.environ.get("MEMORY_TEST_REDIS_URL")
    if not url:
        pytest.skip("set MEMORY_TEST_REDIS_URL for real Redis acceptance")
    import redis

    connection = redis.Redis.from_url(url)
    connection.ping()
    working = RedisWorkingMemory(connection, service)
    memory = service.create(ctx, MemoryCreate(text="Private working state"))
    try:
        working.save(ctx, [memory.memory_id])
        assert working.load(ctx)[0].memory_id == memory.memory_id
        assert b"Private working state" not in connection.get(working.key(ctx))
        service.delete(ctx, memory.memory_id)
        assert working.load(ctx) == []
    finally:
        working.clear(ctx)
        connection.close()
