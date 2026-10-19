"""Retain indexed candidate retrieval for 2048-dimensional cloud embeddings."""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE INDEX ix_memory_vectors_2048_hnsw ON memory_embeddings
            USING hnsw ((vector::halfvec(2048)) halfvec_cosine_ops)
            WHERE dimensions=2048""")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX ix_memory_vectors_2048_hnsw")
