"""Job execution timestamps for observable progress and recovery."""

from alembic import op
from sqlalchemy import Column, DateTime, inspect

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    names = {c["name"] for c in inspect(op.get_bind()).get_columns("background_jobs")}
    for name in ("started_at", "finished_at"):
        if name not in names:
            op.add_column("background_jobs", Column(name, DateTime(timezone=True)))


def downgrade():
    op.drop_column("background_jobs", "finished_at")
    op.drop_column("background_jobs", "started_at")
