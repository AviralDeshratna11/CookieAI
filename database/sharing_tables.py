"""Cross-user visibility grants. A grant exposes only a namespace's SHARED-flagged
memories to another user; it never exposes the rest of that namespace."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Table, Uuid

from database.tables import metadata

shares = Table(
    "namespace_shares",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("namespace_id", Uuid, ForeignKey("namespaces.id"), nullable=False),
    Column("grantee_user_id", Uuid, ForeignKey("users.id"), nullable=False),
    Column("granted_by_user_id", Uuid, ForeignKey("users.id"), nullable=False),
    Column("can_read", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)
