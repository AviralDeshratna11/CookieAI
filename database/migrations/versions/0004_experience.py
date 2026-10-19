from alembic import op

from database.experience_tables import EXPERIENCE_TABLES

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    for table in EXPERIENCE_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(EXPERIENCE_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
