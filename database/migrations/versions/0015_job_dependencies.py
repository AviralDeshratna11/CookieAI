"""Explicit evidence dependencies for targeted deletion and lease cancellation."""

from alembic import op
from sqlalchemy import JSON, Column, inspect, text

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    # Earlier table-creation migrations share current metadata on fresh installs.
    if "dependencies" not in {
        c["name"] for c in inspect(op.get_bind()).get_columns("background_jobs")
    }:
        op.add_column(
            "background_jobs",
            Column("dependencies", JSON, nullable=False, server_default=text("'{}'")),
        )


def downgrade():
    op.drop_column("background_jobs", "dependencies")
