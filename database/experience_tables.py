from sqlalchemy import JSON, Column, ForeignKey, Table, Uuid

from database.tables import metadata

experiences = Table(
    "experiences",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
experience_episodes = Table(
    "experience_episodes",
    metadata,
    Column(
        "experience_id",
        Uuid,
        ForeignKey("experiences.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "episode_id",
        Uuid,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
EXPERIENCE_TABLES = [experiences, experience_episodes]
