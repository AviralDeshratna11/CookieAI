"""Foundation relational state and main vector projection in one transaction."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)

metadata = MetaData()

users = Table("users", metadata, Column("id", Uuid, primary_key=True))
agents = Table(
    "agents",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id"), nullable=False),
)
namespaces = Table(
    "namespaces",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("owner_id", Uuid, ForeignKey("users.id"), nullable=False),
    Column("kind", String(32), nullable=False, default="USER_PRIVATE"),
)
grants = Table(
    "namespace_grants",
    metadata,
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), primary_key=True),
    Column("agent_id", Uuid, ForeignKey("agents.id"), primary_key=True),
    Column("can_read", Boolean, nullable=False),
    Column("can_write", Boolean, nullable=False),
    Column("can_delete", Boolean, nullable=False),
)
sessions = Table(
    "sessions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), nullable=False),
    Column("agent_id", Uuid, ForeignKey("agents.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
messages = Table(
    "messages",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("session_id", Uuid, ForeignKey("sessions.id"), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("session_id", "sequence"),
)
memories = Table(
    "memories",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), nullable=False),
    Column("owner_id", Uuid, ForeignKey("users.id"), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("acl_hash", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("namespace_id", "owner_id", "content_hash", "acl_hash"),
)
Index("ix_memories_namespace_status", memories.c.namespace_id, memories.c.status)
embeddings = Table(
    "memory_embeddings",
    metadata,
    Column(
        "memory_id",
        Uuid,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("model_id", String(200), nullable=False),
    Column("model_version", String(100), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("vector", Vector().with_variant(JSON(), "sqlite"), nullable=False),
)
versions = Table(
    "memory_versions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "memory_id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    ),
    Column("revision", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("memory_id", "revision"),
)
mutations = Table(
    "memory_mutations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("memory_id", Uuid, nullable=False),
    Column("agent_id", Uuid, nullable=False),
    Column("operation", String(40), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("purpose", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
provenance = Table(
    "provenance_edges",
    metadata,
    Column("parent_id", Uuid, primary_key=True),
    Column(
        "child_id",
        Uuid,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("namespace_id", Uuid, nullable=False),
    Column("kind", String(32), nullable=False),
)
outbox = Table(
    "outbox_events",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("object_id", Uuid, nullable=False),
    Column("event_type", String(40), nullable=False),
    Column("correlation_id", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("delivered_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False, default=0),
)
tombstones = Table(
    "deletion_tombstones",
    metadata,
    Column("memory_id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=False),
)
ingestions = Table(
    "ingestion_receipts",
    metadata,
    Column("namespace_id", Uuid, primary_key=True),
    Column("agent_id", Uuid, primary_key=True),
    Column("idempotency_key", String(128), primary_key=True),
    Column("request_hash", String(64), nullable=False),
    Column("memory_ids", JSON, nullable=False),
)

# Freeze the migration's membership before later phases register their tables.
FOUNDATION_TABLES = list(metadata.sorted_tables)
