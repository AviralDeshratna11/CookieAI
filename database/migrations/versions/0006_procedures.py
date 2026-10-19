from alembic import op

from database.procedure_tables import PROCEDURE_TABLES

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    for table in PROCEDURE_TABLES:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for table in reversed(PROCEDURE_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
