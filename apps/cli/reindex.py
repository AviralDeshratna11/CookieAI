"""Offline, namespace-atomic vector cutover. Stop API/workers before invoking."""

import argparse
import json
from contextlib import nullcontext
from uuid import UUID

from sqlalchemy import delete, insert, select

from database import hybrid_tables as h
from database import tables as t
from database.engine import make_engine
from database.repositories.memory import SQLMemoryRepository
from memory.config import Settings
from memory.schemas import Memory
from models.providers import CompatibleEmbedding


def reindex_namespace(engine, ctx, embedder, connection=None):
    """Failure rolls back this namespace; completed namespaces can be skipped on retry."""
    changed = 0
    with nullcontext(connection) if connection is not None else engine.begin() as db:
        repo = SQLMemoryRepository(db, ctx)
        repo.lock_namespace()
        ids = (
            db.execute(
                select(t.memories.c.id).where(
                    t.memories.c.namespace_id == ctx.namespace_id
                )
            )
            .scalars()
            .all()
        )
        for memory_id in ids:
            memory = repo.get(memory_id)
            projection = (
                db.execute(
                    select(t.embeddings).where(t.embeddings.c.memory_id == memory_id)
                )
                .mappings()
                .first()
            )
            if projection and (
                projection["model_id"],
                projection["model_version"],
                projection["dimensions"],
            ) == (embedder.model_id, embedder.version, embedder.dimensions):
                continue
            vector = embedder.embed(memory.canonical_text)
            values = memory.model_dump()
            values.update(
                embedding_model=embedder.model_id,
                embedding_version=embedder.version,
                revision=memory.revision + 1,
            )
            repo.save(Memory.model_validate(values), vector, "REINDEXED")
            changed += 1
        for row in db.execute(
            select(h.entities).where(h.entities.c.namespace_id == ctx.namespace_id)
        ).mappings():
            vector = embedder.embed(row["canonical_name"])
            db.execute(
                delete(h.entity_embeddings).where(
                    h.entity_embeddings.c.entity_id == row["id"]
                )
            )
            db.execute(
                insert(h.entity_embeddings).values(
                    entity_id=row["id"],
                    model_id=embedder.model_id,
                    model_version=embedder.version,
                    dimensions=embedder.dimensions,
                    vector=vector,
                )
            )
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dimensions", required=True, type=int)
    parser.add_argument("--provider-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--offline-confirmed", action="store_true", required=True)
    args = parser.parse_args()
    settings = Settings(
        embedding_model=args.model,
        embedding_version=args.version,
        embedding_dimensions=args.dimensions,
        provider_base_url=args.provider_url,
    )
    from memory.schemas import RequestContext

    credentials = json.loads(settings.credentials_file.read_text(encoding="utf-8"))
    engine = make_engine(settings.database_url)
    seen = set()
    for credential in credentials:
        if credential["namespace_id"] in seen:
            continue
        seen.add(credential["namespace_id"])
        from uuid import uuid4

        ctx = RequestContext(
            user_id=UUID(credential["user_id"]),
            requesting_agent_id=UUID(credential["agent_id"]),
            namespace_id=UUID(credential["namespace_id"]),
            session_id=uuid4(),
            purpose="Offline semantic vector cutover",
            requested_scope="write",
        )
        count = reindex_namespace(engine, ctx, CompatibleEmbedding(settings))
        print(
            json.dumps(
                {
                    "namespace_id": str(ctx.namespace_id),
                    "reindexed": count,
                    "status": "committed",
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
