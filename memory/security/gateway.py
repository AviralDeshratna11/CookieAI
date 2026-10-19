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
