"""Entity vector store and lexical projection.

Revision ID: 0002
"""

from alembic import op

from database.hybrid_tables import HYBRID_TABLES

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    for table in HYBRID_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(HYBRID_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
