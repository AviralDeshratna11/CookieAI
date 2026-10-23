"""Persistent fail-closed namespace disclosure choices."""

from alembic import op

from database.disclosure_tables import disclosure

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    disclosure.create(op.get_bind())
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE namespace_disclosure ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE namespace_disclosure FORCE ROW LEVEL SECURITY")
        op.execute("""CREATE POLICY tenant_isolation ON namespace_disclosure
            USING (namespace_id::text=current_setting('memory.namespace_id',true))
            WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true))""")
        op.execute("REVOKE ALL ON namespace_disclosure FROM PUBLIC")
        for role in ("anon", "authenticated"):
            op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='{role}')
                THEN REVOKE ALL ON namespace_disclosure FROM {role}; END IF; END $$""")


def downgrade():
    disclosure.drop(op.get_bind())
