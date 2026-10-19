from memory.security.gateway import RateLimiter


def test_bounded_rate_limit():
    limiter = RateLimiter(limit=2)
    assert limiter.allow("client")
    assert limiter.allow("client")
    assert not limiter.allow("client")
    assert limiter.allow("other")
