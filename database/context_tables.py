from sqlalchemy import JSON, Column, ForeignKey, Table, Uuid

from database.tables import metadata

goals = Table(
    "goals",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
goal_relations = Table(
    "goal_relations",
    metadata,
    Column(
        "parent_id", Uuid, ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "child_id", Uuid, ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True
    ),
)
CONTEXT_TABLES = [goals, goal_relations]
