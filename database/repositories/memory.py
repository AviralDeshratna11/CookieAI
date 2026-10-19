"""Transaction-scoped repository; every access begins with namespace authorization."""

import hashlib
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select, text, update

from database import tables as t
from memory.schemas import Memory, MessageInput, RequestContext, Status, utcnow
from memory.security.auth import AccessDenied, Conflict, NotFound


class MemoryRepository(Protocol):
    def get(self, memory_id: UUID) -> Memory: ...
    def save(self, memory: Memory, vector: list[float], operation: str) -> None: ...
    def search(
        self, vector: list[float], model_id: str, version: str, limit: int
    ) -> list: ...


class SQLMemoryRepository:
    def __init__(self, connection, context: RequestContext):
        self.db = connection
        self.ctx = context
        if self.db.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT set_config('memory.namespace_id',:namespace,true)"),
                {"namespace": str(context.namespace_id)},
            )
        grant = (
            self.db.execute(
                select(t.grants)
                .join(t.namespaces)
                .join(t.agents, t.grants.c.agent_id == t.agents.c.id)
                .where(
                    t.grants.c.namespace_id == context.namespace_id,
                    t.grants.c.agent_id == context.requesting_agent_id,
                    t.namespaces.c.owner_id == context.user_id,
                    t.agents.c.user_id == context.user_id,
                )
            )
            .mappings()
            .first()
        )
        if (
            not grant
            or not grant[f"can_{context.requested_scope}"]
            or not grant["can_read"]
        ):
            raise AccessDenied("namespace or scope not authorized")

    def lock_namespace(self):
        if self.db.dialect.name == "postgresql":
            lock_id = int.from_bytes(
                hashlib.sha256(self.ctx.namespace_id.bytes).digest()[:8],
                "big",
                signed=True,
            )
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id}
            )
        if self.ctx.execution_job_id:
            from database import operations_tables as operations

            statement = select(operations.jobs.c.id).where(
                operations.jobs.c.id == self.ctx.execution_job_id,
                operations.jobs.c.namespace_id == self.ctx.namespace_id,
                operations.jobs.c.status == "RUNNING",
                operations.jobs.c.lease_token == self.ctx.execution_lease_token,
            )
            if self.db.dialect.name == "postgresql":
                statement = statement.with_for_update()
            if self.db.execute(statement).first() is None:
                raise AccessDenied("background job was canceled or its lease changed")

    def allowed(self, memory):
        return (
            memory.owner_id == self.ctx.user_id
            and (
                not memory.allowed_agent_ids
                or self.ctx.requesting_agent_id in memory.allowed_agent_ids
            )
            and (
                not memory.allowed_project_ids
                or bool(set(memory.allowed_project_ids) & set(self.ctx.project_ids))
            )
        )

    def get(self, memory_id):
        row = self.db.execute(
            select(t.memories.c.payload).where(
                t.memories.c.id == memory_id,
                t.memories.c.namespace_id == self.ctx.namespace_id,
                t.memories.c.owner_id == self.ctx.user_id,
            )
        ).first()
        if row:
            memory = Memory.model_validate(row.payload)
            if self.allowed(memory):
                return memory
        raise NotFound("memory not found")

    @staticmethod
    def valid_at(memory, when=None):
        instant = when or utcnow()
        return (not memory.valid_from or memory.valid_from <= instant) and (
            not memory.valid_until or instant < memory.valid_until
        )

    def recent(self, limit=12, include_history=False, as_of=None):
        rows = self.db.execute(
            select(t.memories.c.payload)
            .where(
                t.memories.c.namespace_id == self.ctx.namespace_id,
                t.memories.c.owner_id == self.ctx.user_id,
                t.memories.c.status.in_(
                    [Status.ACTIVE.value, Status.DISPUTED.value]
                    + (["DORMANT", "ARCHIVED"] if include_history else [])
                    + (["SUPERSEDED"] if as_of else [])
                ),
                (
                    t.memories.c.expires_at.is_(None)
                    | (t.memories.c.expires_at > utcnow())
                ),
            )
            .order_by(t.memories.c.created_at.desc())
        )
        result = []
        for row in rows:
            memory = Memory.model_validate(row.payload)
            if self.allowed(memory) and self.valid_at(memory, as_of):
                result.append(memory)
                if limit is not None and len(result) >= limit:
                    break
        return result

    def duplicate(self, content_hash, acl_hash):
        row = self.db.execute(
            select(t.memories.c.id).where(
                t.memories.c.namespace_id == self.ctx.namespace_id,
                t.memories.c.owner_id == self.ctx.user_id,
                t.memories.c.content_hash == content_hash,
                t.memories.c.acl_hash == acl_hash,
            )
        ).first()
        return self.get(row.id) if row else None

    def audit(self, memory, operation):
        self.db.execute(
            insert(t.mutations).values(
                id=uuid4(),
                namespace_id=self.ctx.namespace_id,
                memory_id=memory.memory_id,
                agent_id=self.ctx.requesting_agent_id,
                operation=operation,
                revision=memory.revision,
                purpose=self.ctx.purpose,
                created_at=utcnow(),
            )
        )
        self.db.execute(
            insert(t.outbox).values(
                id=uuid4(),
                namespace_id=self.ctx.namespace_id,
                object_id=memory.memory_id,
                event_type=f"MEMORY_{operation}",
                correlation_id=self.ctx.session_id,
                created_at=utcnow(),
            )
        )

    @staticmethod
    def acl_hash(memory):
        import json

        acl = [
            memory.privacy_class,
            sorted(map(str, memory.allowed_agent_ids)),
            sorted(map(str, memory.allowed_project_ids)),
            memory.type.value,
            memory.epistemic_type.value,
            sorted(map(str, memory.provenance_ids)),
        ]
        if memory.type.value in {"EPISODIC", "OBSERVATION"}:
            acl.extend([str(memory.source_id), memory.observed_at.isoformat()])
        return hashlib.sha256(json.dumps(acl).encode()).hexdigest()

    def save(self, memory, vector, operation):
        values = dict(
            namespace_id=memory.namespace_id,
            owner_id=memory.owner_id,
            content_hash=memory.content_hash,
            acl_hash=self.acl_hash(memory),
            status=memory.status.value,
            expires_at=memory.expires_at,
            created_at=memory.created_at,
            revision=memory.revision,
            payload=memory.model_dump(mode="json"),
        )
        if operation == "CREATED":
            self.db.execute(insert(t.memories).values(id=memory.memory_id, **values))
        else:
            result = self.db.execute(
                update(t.memories)
                .where(
                    t.memories.c.id == memory.memory_id,
                    t.memories.c.namespace_id == self.ctx.namespace_id,
                    t.memories.c.revision == memory.revision - 1,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise Conflict("memory revision changed")
            self.db.execute(
                delete(t.embeddings).where(t.embeddings.c.memory_id == memory.memory_id)
            )
        self.db.execute(
            insert(t.embeddings).values(
                memory_id=memory.memory_id,
                model_id=memory.embedding_model,
                model_version=memory.embedding_version,
                dimensions=len(vector),
                vector=vector,
            )
        )
        self.db.execute(
            insert(t.versions).values(
                id=uuid4(),
                memory_id=memory.memory_id,
                revision=memory.revision,
                payload=memory.model_dump(mode="json"),
            )
        )
        self.audit(memory, operation)

    def search(
        self, vector, model_id, version, limit, include_history=False, as_of=None
    ):
        statement = (
            select(t.memories.c.payload, t.embeddings.c.vector)
            .join(t.embeddings)
            .where(
                t.memories.c.namespace_id == self.ctx.namespace_id,
                t.memories.c.owner_id == self.ctx.user_id,
                t.memories.c.status.in_(
                    [Status.ACTIVE.value, Status.DISPUTED.value]
                    + (["DORMANT", "ARCHIVED"] if include_history else [])
                    + (["SUPERSEDED"] if as_of else [])
                ),
                (
                    t.memories.c.expires_at.is_(None)
                    | (t.memories.c.expires_at > utcnow())
                ),
                t.embeddings.c.model_id == model_id,
                t.embeddings.c.model_version == version,
                t.embeddings.c.dimensions == len(vector),
            )
        )
        if self.db.dialect.name == "postgresql":
            # Object ACL filtering occurs below before selecting the final candidate pool.
            statement = statement.order_by(
                t.embeddings.c.vector.cosine_distance(vector)
            )
        scored = []
        for row in self.db.execute(statement):
            memory = Memory.model_validate(row.payload)
            if not self.allowed(memory) or not self.valid_at(memory, as_of):
                continue
            similarity = sum(a * float(b) for a, b in zip(vector, row.vector))
            scored.append((memory, max(0.0, min(1.0, similarity))))
        return sorted(scored, key=lambda item: (-item[1], str(item[0].memory_id)))[
            :limit
        ]

    def session(self):
        session = (
            self.db.execute(
                select(t.sessions).where(t.sessions.c.id == self.ctx.session_id)
            )
            .mappings()
            .first()
        )
        if session:
            if (
                session["namespace_id"] != self.ctx.namespace_id
                or session["agent_id"] != self.ctx.requesting_agent_id
            ):
                raise AccessDenied("session is outside the authorized context")
        else:
            self.db.execute(
                insert(t.sessions).values(
                    id=self.ctx.session_id,
                    namespace_id=self.ctx.namespace_id,
                    agent_id=self.ctx.requesting_agent_id,
                    created_at=utcnow(),
                )
            )

    def rolling_messages(self):
        session = (
            self.db.execute(
                select(t.sessions).where(t.sessions.c.id == self.ctx.session_id)
            )
            .mappings()
            .first()
        )
        if session and (
            session["namespace_id"] != self.ctx.namespace_id
            or session["agent_id"] != self.ctx.requesting_agent_id
        ):
            raise AccessDenied("session is outside the authorized context")
        if session is None:
            return []
        return [
            MessageInput.model_validate(row.payload)
            for row in self.db.execute(
                select(t.messages.c.payload)
                .where(t.messages.c.session_id == self.ctx.session_id)
                .order_by(t.messages.c.sequence)
            )
        ]

    def append_messages(self, messages, max_count):
        sequence = (
            self.db.execute(
                select(func.max(t.messages.c.sequence)).where(
                    t.messages.c.session_id == self.ctx.session_id
                )
            ).scalar()
            or 0
        )
        for message in messages:
            sequence += 1
            self.db.execute(
                insert(t.messages).values(
                    id=message.message_id,
                    session_id=self.ctx.session_id,
                    sequence=sequence,
                    payload=message.model_dump(mode="json"),
                )
            )
        self.db.execute(
            delete(t.messages).where(
                t.messages.c.session_id == self.ctx.session_id,
                t.messages.c.sequence <= sequence - max_count,
            )
        )

    def provenance(self, memory_id):
        self.get(memory_id)
        rows = self.db.execute(
            select(t.provenance).where(
                t.provenance.c.child_id == memory_id,
                t.provenance.c.namespace_id == self.ctx.namespace_id,
            )
        )
        result = []
        for row in rows.mappings():
            if row["kind"] == "DERIVED_FROM":
                try:
                    self.get(row["parent_id"])
                except NotFound:
                    continue
            result.append({k: str(v) for k, v in row.items()})
        return result

    def hard_delete(self, memory_id):
        # Remove ALL descendants, not just direct children: no derived text may retain a deleted source.
        pending, removed = [memory_id], set()
        while pending:
            current = pending.pop()
            if current in removed:
                continue
            self.get(
                current
            )  # Fail closed if a cascade would cross object authorization.
            removed.add(current)
            pending.extend(
                self.db.execute(
                    select(t.provenance.c.child_id).where(
                        t.provenance.c.parent_id == current,
                        t.provenance.c.namespace_id == self.ctx.namespace_id,
                        t.provenance.c.kind == "DERIVED_FROM",
                    )
                ).scalars()
            )
        source_messages = set()
        source_sessions = set()
        from memory.graph.service import remove

        remove(self, list(removed))
        from database import operations_tables as operations

        # Pending raw extraction jobs can contain source text; remove them before deletion can be acknowledged.
        self.db.execute(
            delete(operations.jobs).where(
                operations.jobs.c.namespace_id == self.ctx.namespace_id
            )
        )
        for current in removed:
            memory = self.get(current)
            if memory.source_id:
                source_messages.add(memory.source_id)
                source_sessions.add(memory.source_session_id)
            self.audit(memory, "DELETED")
            self.db.execute(
                delete(t.provenance).where(
                    (t.provenance.c.parent_id == current)
                    | (t.provenance.c.child_id == current)
                )
            )
            self.db.execute(delete(t.versions).where(t.versions.c.memory_id == current))
            self.db.execute(
                delete(t.embeddings).where(t.embeddings.c.memory_id == current)
            )
            self.db.execute(delete(t.memories).where(t.memories.c.id == current))
            self.db.execute(
                insert(t.tombstones).values(
                    memory_id=current,
                    namespace_id=self.ctx.namespace_id,
                    deleted_at=utcnow(),
                )
            )
        # Rolling source text must not survive deletion; receipts retain IDs only.
        if source_messages:
            self.db.execute(
                delete(t.messages).where(t.messages.c.id.in_(source_messages))
            )
            from database import source_tables

            self.db.execute(
                delete(source_tables.sources).where(
                    source_tables.sources.c.session_id.in_(source_sessions),
                    source_tables.sources.c.namespace_id == self.ctx.namespace_id,
                )
            )
            self.db.execute(
                delete(t.messages).where(t.messages.c.session_id.in_(source_sessions))
            )
        return removed
