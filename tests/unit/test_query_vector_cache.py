from concurrent.futures import ThreadPoolExecutor

from memory.retrieval.cache import QueryVectorCache


def test_query_cache_is_bounded_and_separates_tenants_and_model_spaces():
    cache = QueryVectorCache(maximum=2)
    calls = []

    def compute():
        calls.append(1)
        return [1.0, 0.0]

    first = cache.get("tenant-a", "model", "1", 2, "private query", compute)
    first[0] = 99
    assert cache.get("tenant-a", "model", "1", 2, "private query", compute) == [
        1.0,
        0.0,
    ]
    assert len(calls) == 1
    cache.get("tenant-b", "model", "1", 2, "private query", compute)
    cache.get("tenant-b", "model", "2", 2, "private query", compute)
    assert len(calls) == 3
    assert len(cache.entries) == 2
    assert "private query" not in repr(cache.entries)


def test_query_cache_shares_only_successful_computations():
    cache = QueryVectorCache()
    calls = []

    def compute():
        calls.append(1)
        return [1.0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(
            pool.map(
                lambda _: cache.get("tenant", "model", "1", 1, "query", compute),
                range(30),
            )
        )
    assert values == [[1.0]] * 30
    assert len(calls) == 1
