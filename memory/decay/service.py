import math

from sqlalchemy import insert, select, update

from database import dynamics_tables as d
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.provenance.policy import evidence_policy
from memory.schemas import Memory, MemoryCreate, utcnow
from memory.security.auth import NotFound, require_scope


class DynamicsService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def decay(self, ctx, now=None, half_life_days=None, limit=1000):
        now = MemoryCreate.aware_time(now or utcnow())
        if half_life_days is not None and half_life_days <= 0:
            raise ValueError("half life must be positive")
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            half_life_days = half_life_days or self.memory.policy(repo).half_life_days
            changed = []
            rows = connection.execute(
                select(t.memories.c.id)
                .where(t.memories.c.namespace_id == ctx.namespace_id)
                .limit(limit)
            )
            for item in rows.scalars():
                try:
                    memory = repo.get(item)
                except NotFound:
                    continue
                if (
                    memory.status.value not in {"ACTIVE", "DORMANT", "ARCHIVED"}
                    or "pinned" in memory.tags
                ):
                    if not (
                        memory.expires_at
                        and memory.expires_at <= now
                        and memory.status.value != "EXPIRED"
                    ):
                        continue
                age = max(0, (now - memory.created_at).total_seconds()) / 86400
                reinforcement = 1 + min(
                    1,
                    math.log1p(
                        memory.successful_use_count + memory.user_confirmation_count
                    )
                    / 5,
                )
                strength = min(
                    1,
                    reinforcement
                    * (0.3 + 0.7 * memory.importance)
                    * 2 ** (-age / (half_life_days * (1 + memory.salience))),
                )
                status = (
                    "EXPIRED"
                    if memory.expires_at and memory.expires_at <= now
                    else (
                        "ARCHIVED"
                        if strength < 0.10
                        else "DORMANT"
                        if strength < 0.20
                        else "ACTIVE"
                    )
                )
                values = memory.model_dump()
                values.update(
                    memory_strength=strength,
                    status=status,
                    revision=memory.revision + 1,
                    updated_at=now,
                )
                revised = Memory.model_validate(values)
                repo.save(
                    revised,
                    self.memory.vector(revised.canonical_text),
                    "ARCHIVED" if status == "ARCHIVED" else "UPDATED",
                )
                from database import reflection_tables as findings
                from memory.insights.lifecycle import seal

                payload = connection.execute(
                    select(findings.insights.c.payload).where(
                        findings.insights.c.id == memory.memory_id
                    )
                ).scalar()
                if payload and status in {"DORMANT", "ARCHIVED", "EXPIRED"}:
                    finding_status = "EXPIRED" if status == "EXPIRED" else "DORMANT"
                    if payload["status"] != finding_status:
                        revised_payload = seal(
                            {**payload, "status": finding_status},
                            [repo.get(identity) for identity in memory.provenance_ids],
                            payload,
                        )
                        connection.execute(
                            update(findings.insights)
                            .where(findings.insights.c.id == memory.memory_id)
                            .values(payload=revised_payload)
                        )
                    self.memory._invalidate_descendants(repo, memory.memory_id)
                changed.append(revised.memory_id)
            return changed

    @require_scope("write")
    def pin(self, ctx, memory_id):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            memory = repo.get(memory_id)
            values = memory.model_dump()
            values.update(
                tags=list(dict.fromkeys(memory.tags + ["pinned"])),
                revision=memory.revision + 1,
                updated_at=utcnow(),
            )
            revised = Memory.model_validate(values)
            repo.save(revised, self.memory.vector(revised.canonical_text), "UPDATED")
            return revised

    @require_scope("write")
    def cluster(self, ctx):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            groups = {}
            for memory in repo.recent(limit=None):
                if memory.type.value == "CONTEXT":
                    continue
                for label in memory.entities + memory.topics:
                    groups.setdefault(label.casefold(), []).append(memory)
            result = []
            for label, evidence in groups.items():
                evidence = evidence[:100]
                if len(evidence) < 2:
                    continue
                ids = [memory.memory_id for memory in evidence]
                summary = (
                    "Thematic cluster "
                    + label
                    + ": "
                    + "; ".join(memory.canonical_text[:150] for memory in evidence[:12])
                )
                canonical = self.memory._create(
                    repo,
                    MemoryCreate(
                        text=summary,
                        type="CONTEXT",
                        epistemic_type="INFERRED",
                        source_type="DERIVED",
                        provenance_ids=ids,
                        **evidence_policy(evidence),
                    ),
                )
                vectors = [
                    self.memory.vector(memory.canonical_text) for memory in evidence
                ]
                centroid = [sum(items) / len(vectors) for items in zip(*vectors)]
                payload = {
                    "cluster_id": str(canonical.memory_id),
                    "label": label,
                    "summary": summary,
                    "centroid": centroid,
                    "activation": 0,
                    "importance": sum(memory.importance for memory in evidence)
                    / len(evidence),
                    "last_updated": utcnow().isoformat(),
                    "member_memory_ids": list(map(str, ids)),
                }
                if not connection.execute(
                    select(d.clusters.c.id).where(
                        d.clusters.c.id == canonical.memory_id
                    )
                ).first():
                    connection.execute(
                        insert(d.clusters).values(
                            id=canonical.memory_id, payload=payload
                        )
                    )
                    for item in ids:
                        connection.execute(
                            insert(d.members).values(
                                cluster_id=canonical.memory_id, memory_id=item
                            )
                        )
                result.append(payload)
            return result
