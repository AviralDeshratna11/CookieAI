"""All compatible-provider calls share this boundary, including embeddings.

Local-only source policy conservatively blocks hosted processing for the entire
namespace. This avoids lossy provenance filtering of derived context.
"""

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from sqlalchemy import insert, select, update

from database import tables as t
from database.disclosure_tables import disclosure
from database.repositories.memory import SQLMemoryRepository
from memory.schemas import StrictModel
from memory.security.auth import AccessDenied, Conflict

_scope = ContextVar("cookieai_disclosure", default=None)
_local = ContextVar("cookieai_local_source", default=False)


class DisclosureDenied(AccessDenied):
    """Safe to explain to an authorized user without revealing private content."""


@contextmanager
def disclosure_scope(memory, ctx, *, local_only=False, connection=None):
    previous = _scope.get()
    if (
        connection is None
        and previous
        and previous[0] is memory
        and previous[1].namespace_id == ctx.namespace_id
    ):
        connection = previous[2]
    token = _scope.set((memory, ctx, connection))
    local_token = _local.set(_local.get() or local_only)
    try:
        yield
    finally:
        _local.reset(local_token)
        _scope.reset(token)


def policy(memory, ctx, connection=None):
    with (
        nullcontext(connection)
        if connection is not None and not connection.closed
        else memory.engine.begin()
    ) as db:
        SQLMemoryRepository(db, ctx.model_copy(update={"requested_scope": "read"}))
        row = (
            db.execute(
                select(disclosure).where(disclosure.c.namespace_id == ctx.namespace_id)
            )
            .mappings()
            .first()
        )
        protected = (
            db.execute(
                select(t.memories.c.id)
                .where(
                    t.memories.c.namespace_id == ctx.namespace_id,
                    t.memories.c.payload["disclosure"].as_string() == "LOCAL_ONLY",
                )
                .limit(1)
            ).first()
            is not None
        )
    return {
        "mode": row["mode"] if row else "APPROVED_CLOUD",
        "revision": row["revision"] if row else 0,
        "local_only_sources": protected,
        "effective_hosted_allowed": memory.settings.cloud_disclosure_enabled
        and (row["mode"] if row else "APPROVED_CLOUD") == "APPROVED_CLOUD"
        and not protected,
        "scope": "Entire namespace; local-only sources block all hosted model operations",
    }


class DisclosureChange(StrictModel):
    mode: Literal["LOCAL_ONLY", "APPROVED_CLOUD"]
    expected_revision: int = Field(ge=0)


def change_policy(memory, ctx, body):
    with memory.engine.begin() as db:
        repo = SQLMemoryRepository(
            db, ctx.model_copy(update={"requested_scope": "write"})
        )
        repo.lock_namespace()
        row = (
            db.execute(
                select(disclosure).where(disclosure.c.namespace_id == ctx.namespace_id)
            )
            .mappings()
            .first()
        )
        if (row["revision"] if row else 0) != body.expected_revision:
            raise Conflict("Disclosure policy changed")
        values = {"mode": body.mode, "revision": body.expected_revision + 1}
        if row:
            db.execute(
                update(disclosure)
                .where(disclosure.c.namespace_id == ctx.namespace_id)
                .values(**values)
            )
        else:
            db.execute(
                insert(disclosure).values(namespace_id=ctx.namespace_id, **values)
            )
    return policy(memory, ctx)


def enforce(settings, base_url):
    """Recheck current persisted policy before EACH call, never trust a model flag."""
    scoped = _scope.get()
    restricted = _local.get() or not settings.cloud_disclosure_enabled
    if scoped:
        current = policy(*scoped)
        restricted |= (
            current["mode"] != "APPROVED_CLOUD" or current["local_only_sources"]
        )
    if restricted:
        # Exact administrator-provisioned endpoints, not hostname substring tests.
        normalized = base_url.rstrip("/")
        if normalized not in {
            value.rstrip("/") for value in settings.local_provider_urls
        }:
            raise DisclosureDenied(
                "Hosted inference is unavailable under local-only policy"
            )
        parsed = urlparse(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
        ):
            raise DisclosureDenied("Invalid local provider endpoint")
