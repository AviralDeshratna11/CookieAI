"""Canonical memory, vector projection and relational audit foundation.

Revision ID: 0001
Revises: none
"""

from alembic import op

from database.tables import FOUNDATION_TABLES, metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    metadata.create_all(op.get_bind(), tables=FOUNDATION_TABLES, checkfirst=False)


def downgrade():
    metadata.drop_all(op.get_bind(), tables=FOUNDATION_TABLES, checkfirst=False)
