from alembic import op

from database.dynamics_tables import DYNAMICS_TABLES

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    for table in DYNAMICS_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(DYNAMICS_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
