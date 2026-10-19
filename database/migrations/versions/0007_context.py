from alembic import op

from database.context_tables import CONTEXT_TABLES

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    for table in CONTEXT_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(CONTEXT_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
