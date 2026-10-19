"""Bounded ephemeral query vectors only; never cache retrieved memories or source text."""

import hashlib
import threading
import time
from collections import OrderedDict


class QueryVectorCache:
    def __init__(self, ttl=60, maximum=256):
        self.ttl, self.maximum = ttl, maximum
        self.entries = OrderedDict()
        self.lock = threading.Lock()
        self.pending = {}

    def get(self, namespace, model, version, dimensions, query, compute):
        if self.ttl <= 0:
            return compute()
        key = hashlib.sha256(
            str((namespace, model, version, dimensions, query)).encode()
        ).digest()
        with self.lock:
            entry = self.entries.get(key)
            if entry and entry[0] > time.monotonic():
                self.entries.move_to_end(key)
                return list(entry[1])
            per_query = self.pending.setdefault(key, threading.Lock())
        try:
            with per_query:
                with self.lock:
                    entry = self.entries.get(key)
                    if entry and entry[0] > time.monotonic():
                        return list(entry[1])
                value = compute()
                with self.lock:
                    self.entries[key] = (time.monotonic() + self.ttl, tuple(value))
                    self.entries.move_to_end(key)
                    while len(self.entries) > self.maximum:
                        self.entries.popitem(last=False)
                return list(value)
        finally:
            with self.lock:
                if self.pending.get(key) is per_query:
                    self.pending.pop(key, None)
