import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from memory.security.gateway import RedisRateLimiter


def test_ingress_budget_is_shared_and_atomic_between_instances():
    url = os.environ.get("MEMORY_TEST_REDIS_URL")
    if not url:
        pytest.skip("set MEMORY_TEST_REDIS_URL")
    import redis

    connection = redis.Redis.from_url(url)
    prefix = "test.limit:" + uuid4().hex + ":"
    first = RedisRateLimiter(connection, limit=7, prefix=prefix)
    second = RedisRateLimiter(connection, limit=7, prefix=prefix)
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(
            pool.map(
                lambda index: (first if index % 2 else second).allow("same-client"),
                range(30),
            )
        )
    assert sum(accepted) == 7
    for key in connection.scan_iter(match=prefix + "*"):
        assert connection.ttl(key) > 0
        connection.delete(key)
    connection.close()
