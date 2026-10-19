from alembic import op

from database.operations_tables import OPERATIONS_TABLES

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    for table in OPERATIONS_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(OPERATIONS_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
