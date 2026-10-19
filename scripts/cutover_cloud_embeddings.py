"""Offline all-namespace embedding cutover; requires stopped API/worker writers."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from dotenv import dotenv_values
from sqlalchemy import create_engine, select, text

from apps.cli.reindex import reindex_namespace
from database import hybrid_tables as h
from database import tables as t
from memory.config import Settings
from memory.schemas import Memory, RequestContext
from models.providers import CompatibleEmbedding, validate_vector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-confirmed", action="store_true", required=True)
    parser.parse_args()
    settings = Settings(_env_file=(".env", ".env.cloud"))
    engine = create_engine(
        dotenv_values(".env.supabase")["MEMORY_HOSTED_MIGRATION_DATABASE_URL"]
    )
    target = CompatibleEmbedding(settings)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": target.model_id,
        "version": target.version,
        "dimensions": target.dimensions,
    }
    cache_path = Path("backups/cloud-embedding-cache.json")
    try:
        with engine.connect() as db:
            memories = [
                Memory.model_validate(p)
                for p in db.execute(select(t.memories.c.payload)).scalars()
            ]
            entities = db.execute(select(h.entities.c.canonical_name)).scalars().all()
            grants = db.execute(
                select(t.namespaces.c.id, t.namespaces.c.owner_id, t.grants.c.agent_id)
                .join(t.grants, t.grants.c.namespace_id == t.namespaces.c.id)
                .where(t.grants.c.can_read.is_(True), t.grants.c.can_write.is_(True))
            ).all()
        contexts = {}
        credentials = json.loads(settings.credentials_file.read_text())
        for ns, owner, agent in grants:
            if ns not in contexts:
                contexts[ns] = RequestContext(
                    user_id=owner,
                    requesting_agent_id=agent,
                    namespace_id=ns,
                    session_id=uuid4(),
                    purpose="Offline cloud embedding migration",
                    requested_scope="write",
                )
        for credential in credentials:
            ns = UUID(credential["namespace_id"])
            if ns in contexts:
                contexts[ns] = contexts[ns].model_copy(
                    update={"requesting_agent_id": UUID(credential["agent_id"])}
                )
        for memory in memories:
            ctx = contexts[memory.namespace_id]
            if (
                memory.allowed_agent_ids
                and ctx.requesting_agent_id not in memory.allowed_agent_ids
            ):
                raise ValueError("Authorized reindex agent does not cover every memory")
            ctx.project_ids = list(
                set(ctx.project_ids) | set(memory.allowed_project_ids)
            )
        snapshot = {str(m.memory_id): m.model_dump(mode="json") for m in memories}
        texts = list(dict.fromkeys([m.canonical_text for m in memories] + entities))
        signature = hashlib.sha256(
            (target.model_id + target.version + str(target.dimensions)).encode()
        ).hexdigest()
        cache = {"signature": signature, "vectors": {}}
        if cache_path.exists():
            existing = json.loads(cache_path.read_text())
            if existing.get("signature") == signature:
                cache = existing
        missing = [item for item in texts if item not in cache["vectors"]]
        cache_path.parent.mkdir(exist_ok=True)
        for start in range(0, len(missing), 4):
            batch = missing[start : start + 4]
            vectors = target.embed_many(batch)
            cache["vectors"].update(zip(batch, vectors))
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
            print(
                "Prepared vectors: "
                + str(min(start + 4, len(missing)))
                + "/"
                + str(len(missing)),
                flush=True,
            )

        class Cached:
            model_id = target.model_id
            version = target.version
            dimensions = target.dimensions

            def embed(self, value):
                return validate_vector(cache["vectors"][value], self.dimensions)

        counts = {}
        with engine.begin() as db:
            db.execute(text("SET LOCAL lock_timeout='15s'"))
            current = {
                str(m["memory_id"]): m
                for m in db.execute(select(t.memories.c.payload)).scalars()
            }
            if current != snapshot:
                raise ValueError(
                    "Memories changed while preparing vectors; stop writers and retry"
                )
            for ns, ctx in contexts.items():
                counts[str(ns)] = reindex_namespace(
                    engine, ctx, Cached(), connection=db
                )
            current_ids = set(db.execute(select(t.memories.c.id)).scalars())
            if current_ids != {m.memory_id for m in memories}:
                raise ValueError("Canonical IDs changed")
            for table in (t.embeddings, h.entity_embeddings):
                spaces = db.execute(
                    select(
                        table.c.model_id, table.c.model_version, table.c.dimensions
                    ).distinct()
                ).all()
                if any(
                    tuple(row) != (target.model_id, target.version, target.dimensions)
                    for row in spaces
                ):
                    raise ValueError("Projection spaces differ")
        report.update(
            namespaces=counts,
            memories_preserved=len(memories),
            entity_projections=len(entities),
            all_namespaces_committed_atomically=True,
        )
        Path("docs/cloud-embedding-cutover-results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
    except Exception as error:
        print(
            "Cutover failed: "
            + type(error).__name__
            + "; database changes rolled back if the transaction did not commit. Credentials were not printed."
        )
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
