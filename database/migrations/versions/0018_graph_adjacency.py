"""Index reverse graph adjacency for bounded frontier retrieval.

Prepared for review; this request does not apply migrations to hosted storage.
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_graph_edges_namespace_target", "graph_edges", ["namespace_id", "target_id"]
    )


def downgrade():
    op.drop_index("ix_graph_edges_namespace_target", table_name="graph_edges")
