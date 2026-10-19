"""Expression indexes for the configured Nomic model and bounded worker lookups."""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    # Mixed-dimensional historical projections require a dimension-filtered index.
    op.execute("""CREATE INDEX ix_memory_vectors_768_hnsw ON memory_embeddings
        USING hnsw ((vector::vector(768)) vector_cosine_ops) WHERE dimensions=768""")
    op.execute(
        "CREATE INDEX ix_outbox_pending_namespace ON outbox_events(namespace_id,created_at) WHERE delivered_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_jobs_namespace_ready ON background_jobs(namespace_id,status,available_at,priority)"
    )
    op.execute(
        "CREATE INDEX ix_reflection_cursor_namespace ON reflection_jobs(namespace_id,cursor_time DESC)"
    )
    op.execute(
        "CREATE INDEX ix_features_namespace_changed ON episode_features(namespace_id,created_at)"
    )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for name in (
        "ix_memory_vectors_768_hnsw",
        "ix_outbox_pending_namespace",
        "ix_jobs_namespace_ready",
        "ix_reflection_cursor_namespace",
        "ix_features_namespace_changed",
    ):
        op.execute(f"DROP INDEX {name}")
