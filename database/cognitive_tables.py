"""Persistent derived continuity and replay-safe assistant turns."""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)

from database.tables import metadata

snapshots = Table(
    "continuity_snapshots",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("scope_hash", String(64), nullable=False),
    Column("evidence_revisions", JSON, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("namespace_id", "scope_hash"),
)

turns = Table(
    "agent_turns",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("agent_id", Uuid, nullable=False),
    Column("session_id", Uuid, nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("status", String(24), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("response", JSON),
    Column("context_refs", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("namespace_id", "agent_id", "idempotency_key"),
)

COGNITIVE_TABLES = [snapshots, turns]
