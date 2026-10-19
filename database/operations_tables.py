from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Uuid,
)

from database.tables import metadata

jobs = Table(
    "background_jobs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("idempotency_key", String(200), nullable=False, unique=True),
    Column("queue", String(50), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("status", String(20), nullable=False),
    Column("retry_count", Integer, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("lease_until", DateTime(timezone=True)),
    Column("lease_token", Uuid),
    Column("last_error", String(200)),
)
Index("ix_jobs_ready", jobs.c.status, jobs.c.available_at, jobs.c.priority)
retrieval_events = Table(
    "retrieval_events",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("agent_id", Uuid, nullable=False),
    Column("session_id", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)
access_events = Table(
    "memory_access_events",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("memory_id", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)
tenant_policies = Table(
    "tenant_policies",
    metadata,
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
OPERATIONS_TABLES = [jobs, retrieval_events, access_events, tenant_policies]
