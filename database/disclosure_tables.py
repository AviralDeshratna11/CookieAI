"""Namespace disclosure policy, independent of model-selected content."""

from sqlalchemy import Column, ForeignKey, Integer, String, Table, Uuid

from database.tables import metadata

disclosure = Table(
    "namespace_disclosure",
    metadata,
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), primary_key=True),
    Column("mode", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
)
