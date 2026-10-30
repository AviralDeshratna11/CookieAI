"""Shared plumbing for the long-term-memory benchmark harnesses
(benchmark_locomo.py, benchmark_longmemeval.py, benchmark_memory_arena_proxy.py):
an isolated per-conversation namespace so samples never bleed into each other
or into real personal data, and one place to load the real provider config."""

import json
import time
from pathlib import Path

import httpx
from sqlalchemy import insert

from database import tables as t
from memory.config import Settings


def load_settings(live, database_url):
    """--live reads this machine's real provider config, merging .env.cloud
    on top of .env (the same precedence `docker compose --env-file .env
    --env-file .env.cloud` uses) since plain `Settings()` only reads .env,
    which points at a Docker-internal address that doesn't resolve outside
    a container. Offline mode never touches real credentials at all."""
    if not live:
        return Settings(
            database_url=database_url,
            embedding_backend="hash-test",
            cloud_disclosure_enabled=False,
        )
    return Settings(_env_file=(".env", ".env.cloud"), database_url=database_url)


def call_with_retry(fn, attempts=5, base_delay=5):
    """A multi-hour --live run must not die on one transient rate limit or
    network blip; retry with backoff, then let a persistent failure surface
    to the caller so it can be recorded per-question instead of crashing
    everything already completed."""
    for attempt in range(attempts):
        try:
            return fn()
        except httpx.HTTPError:
            if attempt == attempts - 1:
                raise
            time.sleep(base_delay * (2**attempt))


def checkpoint(report_builder, out_path):
    """Write partial progress after every sample/instance so a late failure
    (or the user stopping the run) never loses hours of completed work."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report_builder(), indent=2), encoding="utf-8")


def provision(engine, ctx):
    with engine.begin() as db:
        db.execute(insert(t.users).values(id=ctx.user_id))
        db.execute(
            insert(t.agents).values(id=ctx.requesting_agent_id, user_id=ctx.user_id)
        )
        db.execute(
            insert(t.namespaces).values(
                id=ctx.namespace_id, owner_id=ctx.user_id, kind="USER_PRIVATE"
            )
        )
        db.execute(
            insert(t.grants).values(
                namespace_id=ctx.namespace_id,
                agent_id=ctx.requesting_agent_id,
                can_read=True,
                can_write=True,
                can_delete=True,
            )
        )
