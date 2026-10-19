"""Higher-order objects retain canonical memory IDs so provenance deletion remains transitive."""

from sqlalchemy import JSON, Column, ForeignKey, Table, Uuid

from database.tables import metadata

episodes = Table(
    "episodes",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
episode_memories = Table(
    "episode_memories",
    metadata,
    Column(
        "episode_id",
        Uuid,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "memory_id",
        Uuid,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
EPISODE_TABLES = [episodes, episode_memories]
