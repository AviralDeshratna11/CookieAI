"""Asynchronous extractive continuity, partitioned by evidence authorization."""

import hashlib
import json
from collections import defaultdict
from uuid import UUID

from sqlalchemy import select, update

from database import cognitive_tables as c
from database.repositories.memory import SQLMemoryRepository
from memory.provenance.policy import evidence_policy
from memory.schemas import Memory, MemoryCreate, utcnow
from memory.security.auth import NotFound, require_scope


class ContinuityService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def build(self, ctx):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            groups = defaultdict(list)
            for memory in repo.recent(limit=200):
                if (
                    memory.status.value != "ACTIVE"
                    or memory.source_type == "DERIVED"
                    or not repo.valid_at(memory)
                ):
                    continue
                scope = json.dumps(
                    evidence_policy([memory]), sort_keys=True, default=str
                )
                groups[scope].append(memory)
            result = []
            for scope, items in groups.items():
                source = sorted(
                    items, key=lambda m: (-m.importance, -m.updated_at.timestamp())
                )[:20]
                revisions = {str(m.memory_id): m.revision for m in source}
                key = hashlib.sha256(scope.encode()).hexdigest()
                previous = (
                    db.execute(
                        select(c.snapshots).where(
                            c.snapshots.c.namespace_id == ctx.namespace_id,
                            c.snapshots.c.scope_hash == key,
                        )
                    )
                    .mappings()
                    .first()
                )
                if previous and previous["evidence_revisions"] == revisions:
                    try:
                        if repo.get(previous["id"]).status.value == "ACTIVE":
                            result.append(previous["id"])
                            continue
                    except NotFound:
                        pass
                entries = [
                    {
                        "memory_id": str(m.memory_id),
                        "type": m.type.value,
                        "text": m.text[:1000],
                        "excerpt": len(m.text) > 1000,
                        "epistemic_type": m.epistemic_type.value,
                        "truth_confidence": m.truth_confidence,
                    }
                    for m in source
                ]
                description = (
                    "Derived continuity snapshot; source statements retain their original epistemic labels.\n"
                    + "\n".join(
                        f"[{item['epistemic_type']}] {item['text']}" for item in entries
                    )
                )
                # Bound the canonical summary without losing attribution.
                while len(description) > 15000 and len(source) > 1:
                    source.pop()
                    entries.pop()
                    description = "Derived continuity snapshot:\n" + "\n".join(
                        f"[{item['epistemic_type']}] {item['text'][:1000]}"
                        for item in entries
                    )
                revisions = {str(m.memory_id): m.revision for m in source}
                ids = [m.memory_id for m in source]
                if previous:
                    old = repo.get(previous["id"])
                    values = old.model_dump()
                    values.update(
                        text=description,
                        canonical_text=description,
                        content_hash=hashlib.sha256(description.encode()).hexdigest(),
                        semantic_hash=hashlib.sha256(
                            description.casefold().encode()
                        ).hexdigest(),
                        provenance_ids=ids,
                        status="ACTIVE",
                        revision=old.revision + 1,
                        updated_at=utcnow(),
                    )
                    snapshot = Memory.model_validate(values)
                    repo.save(snapshot, self.memory.vector(description), "UPDATED")
                    from sqlalchemy import delete, insert

                    from database import tables as t

                    db.execute(
                        delete(t.provenance).where(
                            t.provenance.c.child_id == snapshot.memory_id,
                            t.provenance.c.kind == "DERIVED_FROM",
                        )
                    )
                    for identity in ids:
                        db.execute(
                            insert(t.provenance).values(
                                parent_id=identity,
                                child_id=snapshot.memory_id,
                                namespace_id=ctx.namespace_id,
                                kind="DERIVED_FROM",
                            )
                        )
                else:
                    snapshot = self.memory._create(
                        repo,
                        MemoryCreate(
                            text=description,
                            type="AUTOBIOGRAPHICAL",
                            epistemic_type="INFERRED",
                            source_type="DERIVED",
                            provenance_ids=ids,
                            tags=["continuity:v1"],
                            **evidence_policy(source),
                        ),
                    )
                values = dict(
                    evidence_revisions=revisions,
                    payload={
                        "entries": entries,
                        "derivation": "EXTRACTIVE",
                        "coverage": "At most 20 sources per authorization partition from 200 recent authorized records",
                        "trust": "Untrusted derived context; not independent evidence",
                    },
                    created_at=utcnow(),
                )
                if previous:
                    db.execute(
                        update(c.snapshots)
                        .where(c.snapshots.c.id == snapshot.memory_id)
                        .values(**values)
                    )
                else:
                    db.execute(
                        c.snapshots.insert().values(
                            id=snapshot.memory_id,
                            namespace_id=ctx.namespace_id,
                            scope_hash=key,
                            **values,
                        )
                    )
                result.append(snapshot.memory_id)
            return result

    @require_scope("read")
    def load(self, ctx):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            result = []
            rows = (
                db.execute(
                    select(c.snapshots)
                    .where(c.snapshots.c.namespace_id == ctx.namespace_id)
                    .limit(20)
                )
                .mappings()
                .all()
            )
            ids = {row["id"] for row in rows}
            ids.update(
                UUID(identity) for row in rows for identity in row["evidence_revisions"]
            )
            permitted = repo.get_many(ids, strict=False)
            for row in rows:
                try:
                    memory = permitted[row["id"]]
                    if memory.status.value != "ACTIVE":
                        continue
                    for identity, revision in row["evidence_revisions"].items():
                        source = permitted[UUID(identity)]
                        if (
                            source.revision != revision
                            or source.status.value != "ACTIVE"
                            or not repo.valid_at(source)
                        ):
                            raise NotFound()
                except (NotFound, KeyError):
                    continue
                result.append(
                    {
                        "memory_id": str(memory.memory_id),
                        "epistemic_type": "INFERRED",
                        **row["payload"],
                        "evidence_revisions": row["evidence_revisions"],
                    }
                )
            return result
