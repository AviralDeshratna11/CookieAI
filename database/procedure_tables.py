from sqlalchemy import JSON, Column, ForeignKey, Table, Uuid

from database.tables import metadata

procedures = Table(
    "procedures",
    metadata,
    Column("id", Uuid, ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
procedure_experiences = Table(
    "procedure_experiences",
    metadata,
    Column(
        "procedure_id",
        Uuid,
        ForeignKey("procedures.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "experience_id",
        Uuid,
        ForeignKey("experiences.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
PROCEDURE_TABLES = [procedures, procedure_experiences]
