"""Redis working state contains references only. Every read resolves current ACLs and deletion state."""

import json

from memory.security.auth import NotFound


class RedisWorkingMemory:
    def __init__(self, redis, memory, ttl_seconds=3600):
        self.redis, self.memory, self.ttl = redis, memory, ttl_seconds

    def key(self, ctx):
        return f"memory:working:{ctx.namespace_id}:{ctx.requesting_agent_id}:{ctx.session_id}"

    def save(self, ctx, memory_ids):
        for item in memory_ids:
            self.memory.get(ctx, item)
        self.redis.setex(
            self.key(ctx), self.ttl, json.dumps(list(map(str, memory_ids)))
        )

    def load(self, ctx):
        from uuid import UUID

        payload = self.redis.get(self.key(ctx))
        if payload is None:
            return []
        result = []
        for item in json.loads(payload):
            try:
                result.append(self.memory.get(ctx, UUID(item)))
            except NotFound:
                pass
        return result

    def clear(self, ctx):
        self.redis.delete(self.key(ctx))
