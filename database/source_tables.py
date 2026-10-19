"""Durable evidence is independent of the ten-message working buffer."""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Table, Uuid

from database.tables import metadata

sources = Table(
    "raw_sources",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), nullable=False),
    Column("session_id", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)
