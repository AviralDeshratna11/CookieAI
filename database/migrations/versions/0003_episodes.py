"""Episode payload and atomic evidence links."""

from alembic import op

from database.learning_tables import EPISODE_TABLES

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    for table in EPISODE_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(EPISODE_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
