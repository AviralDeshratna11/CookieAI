from alembic import op

from database.source_tables import sources

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    sources.create(op.get_bind(), checkfirst=False)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE raw_sources ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE raw_sources FORCE ROW LEVEL SECURITY")
        predicate = "namespace_id::text=current_setting('memory.namespace_id',true)"
        op.execute(
            f"CREATE POLICY tenant_isolation ON raw_sources USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade():
    sources.drop(op.get_bind(), checkfirst=False)
