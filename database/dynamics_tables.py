from sqlalchemy import JSON, Column, ForeignKey, Table, Uuid

from database.tables import metadata

clusters = Table(
    "memory_clusters",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
members = Table(
    "cluster_members",
    metadata,
    Column(
        "cluster_id",
        Uuid,
        ForeignKey("memory_clusters.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "memory_id",
        Uuid,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
open_loops = Table(
    "open_loops",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
prospective = Table(
    "prospective_memories",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
DYNAMICS_TABLES = [clusters, members, open_loops, prospective]
