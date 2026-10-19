from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Uuid,
)

from database.tables import metadata

insights = Table(
    "insights",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("feature_hash", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
)
insight_evidence = Table(
    "insight_evidence",
    metadata,
    Column(
        "insight_id",
        Uuid,
        ForeignKey("insights.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "episode_id",
        Uuid,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
insight_counterexamples = Table(
    "insight_counterexamples",
    metadata,
    Column(
        "insight_id",
        Uuid,
        ForeignKey("insights.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "episode_id",
        Uuid,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
features = Table(
    "episode_features",
    metadata,
    Column("namespace_id", Uuid, nullable=False),
    Column(
        "episode_id",
        Uuid,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("feature_hash", String(64), primary_key=True),
    Column("description", String(2000), nullable=False),
    Column("failure", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_features_namespace_key", features.c.namespace_id, features.c.feature_hash)
jobs = Table(
    "reflection_jobs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, nullable=False),
    Column("cursor_time", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)
REFLECTION_TABLES = [
    insights,
    insight_evidence,
    insight_counterexamples,
    features,
    jobs,
]
