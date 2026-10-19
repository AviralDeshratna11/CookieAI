from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)

from database.tables import metadata

lexical = Table(
    "memory_lexical",
    metadata,
    Column(
        "memory_id",
        Uuid,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("terms", JSON, nullable=False),
)
entities = Table(
    "entities",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), nullable=False),
    Column("canonical_name", String(500), nullable=False),
    Column("normalized_name", String(500), nullable=False),
    Column("entity_type", String(40), nullable=False),
    Column("resolution_confidence", JSON, nullable=False),
    UniqueConstraint("namespace_id", "normalized_name"),
)
entity_aliases = Table(
    "entity_aliases",
    metadata,
    Column(
        "entity_id",
        Uuid,
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("alias", String(500), primary_key=True),
)
entity_embeddings = Table(
    "entity_embeddings",
    metadata,
    Column(
        "entity_id",
        Uuid,
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("model_id", String(200), nullable=False),
    Column("model_version", String(100), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("vector", Vector().with_variant(JSON(), "sqlite"), nullable=False),
)
memory_entities = Table(
    "memory_entities",
    metadata,
    Column(
        "memory_id",
        Uuid,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "entity_id",
        Uuid,
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

HYBRID_TABLES = [lexical, entities, entity_aliases, entity_embeddings, memory_entities]
