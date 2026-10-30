"""Cross-user namespace sharing grants, visible to both the granting namespace
and the grantee's own session; writable only from the granting namespace."""

from alembic import op

from database.sharing_tables import shares

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    shares.create(op.get_bind())
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE namespace_shares ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE namespace_shares FORCE ROW LEVEL SECURITY")
        op.execute("""CREATE POLICY tenant_isolation ON namespace_shares
            USING (
                namespace_id::text = current_setting('memory.namespace_id', true)
                OR grantee_user_id::text = current_setting('memory.user_id', true)
            )
            WITH CHECK (namespace_id::text = current_setting('memory.namespace_id', true))""")
        op.execute("REVOKE ALL ON namespace_shares FROM PUBLIC")
        for role in ("anon", "authenticated"):
            op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='{role}')
                THEN REVOKE ALL ON namespace_shares FROM {role}; END IF; END $$""")


def downgrade():
    shares.drop(op.get_bind())
