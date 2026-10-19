"""Local deployment rate limiter; put distributed rate limiting at a multi-replica ingress."""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit=120, window_seconds=60, max_clients=10000):
        self.limit, self.window, self.max_clients = limit, window_seconds, max_clients
        self.requests = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key):
        with self.lock:
            now = time.monotonic()
            if len(self.requests) >= self.max_clients and key not in self.requests:
                stale = [
                    client
                    for client, events in self.requests.items()
                    if not events or events[-1] < now - self.window
                ]
                for client in stale:
                    del self.requests[client]
                if len(self.requests) >= self.max_clients:
                    return False
            events = self.requests[key]
            while events and events[0] < now - self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


class RedisRateLimiter:
    """Atomic shared ingress budget. Provider failures are handled by the gateway."""

    SCRIPT = """
    local value = redis.call('INCR', KEYS[1])
    if value == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
    return value <= tonumber(ARGV[2]) and 1 or 0
    """

    def __init__(
        self, connection, limit=120, window_seconds=60, prefix="memory.ingress:"
    ):
        self.connection, self.limit = connection, limit
        self.window_ms = int(window_seconds * 1000)
        self.prefix = prefix

    def allow(self, key):
        import hashlib

        digest = hashlib.sha256(key.encode()).hexdigest()
        return bool(
            self.connection.eval(
                self.SCRIPT, 1, self.prefix + digest, self.window_ms, self.limit
            )
        )
