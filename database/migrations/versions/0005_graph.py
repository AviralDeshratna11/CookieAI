from alembic import op

from database.graph_tables import GRAPH_TABLES

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    for table in GRAPH_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(GRAPH_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
