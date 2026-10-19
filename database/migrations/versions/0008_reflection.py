from alembic import op

from database.reflection_tables import REFLECTION_TABLES

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    for table in REFLECTION_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(REFLECTION_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
