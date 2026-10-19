"""Read only the namespace-scoped worker heartbeat; no model calls."""

import os
from pathlib import Path

import redis

from memory.config import Settings
from memory.schemas import RequestContext


def main():
    ctx = RequestContext.model_validate_json(
        os.environ.get("MEMORY_WORKER_CONTEXT")
        or Path(
            os.environ.get("MEMORY_WORKER_CONTEXT_FILE", "config/worker-context.json")
        ).read_text(encoding="utf-8")
    )
    connection = redis.Redis.from_url(
        Settings().redis_url, socket_timeout=3, socket_connect_timeout=3
    )
    alive = connection.exists(
        f"memory.worker:{ctx.namespace_id}:{ctx.requesting_agent_id}"
    )
    connection.close()
    raise SystemExit(0 if alive else 1)


if __name__ == "__main__":
    main()
