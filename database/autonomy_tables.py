"""Durable task state, bound to canonical memory for ACLs and erasure."""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)

from database.tables import metadata

tasks = Table(
    "autonomous_tasks",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("agent_id", Uuid, nullable=False),
    Column("goal_id", Uuid, ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("status", String(24), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("execution_context", JSON, nullable=False),
    Column("next_run_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("namespace_id", "agent_id", "idempotency_key"),
)
Index(
    "ix_autonomous_tasks_due", tasks.c.namespace_id, tasks.c.status, tasks.c.next_run_at
)
runs = Table(
    "autonomous_task_runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "task_id",
        Uuid,
        ForeignKey("autonomous_tasks.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("namespace_id", Uuid, nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("status", String(24), nullable=False),
    Column("lease_token", Uuid, nullable=False),
    Column("lease_until", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    UniqueConstraint("task_id", "sequence"),
)
Index("ix_autonomous_runs_task", runs.c.task_id, runs.c.sequence)
usage = Table(
    "autonomous_daily_usage",
    metadata,
    Column("namespace_id", Uuid, primary_key=True),
    Column("agent_id", Uuid, primary_key=True),
    Column("day", String(10), primary_key=True),
    Column("tool_calls", Integer, nullable=False),
    Column("model_calls", Integer, nullable=False),
)
charges = Table(
    "autonomous_usage_charges",
    metadata,
    Column("namespace_id", Uuid, primary_key=True),
    Column("event_id", Uuid, primary_key=True),
    Column("agent_id", Uuid, nullable=False),
    Column("day", String(10), nullable=False),
    Column("kind", String(12), nullable=False),
)
events = Table(
    "autonomous_event_receipts",
    metadata,
    Column(
        "task_id",
        Uuid,
        ForeignKey("autonomous_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("event_id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("event_type", String(40), nullable=False),
    Column("seen_at", DateTime(timezone=True), nullable=False),
)
AUTONOMY_TABLES = [tasks, runs, usage, charges, events]
