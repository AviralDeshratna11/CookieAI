from sqlalchemy import JSON, Column, ForeignKey, String, Table, UniqueConstraint, Uuid

from database.tables import metadata

nodes = Table(
    "graph_nodes",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), nullable=False),
    Column("kind", String(40), nullable=False),
)
edges = Table(
    "graph_edges",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), nullable=False),
    Column(
        "source_id",
        Uuid,
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "target_id",
        Uuid,
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("relationship_type", String(40), nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("namespace_id", "source_id", "target_id", "relationship_type"),
)
edge_evidence = Table(
    "graph_edge_evidence",
    metadata,
    Column(
        "edge_id",
        Uuid,
        ForeignKey("graph_edges.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "memory_id",
        Uuid,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
GRAPH_TABLES = [nodes, edges, edge_evidence]
