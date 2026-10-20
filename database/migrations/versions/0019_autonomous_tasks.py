"""Namespace-isolated autonomous tasks and execution/verifier journals."""

from alembic import op

from database.autonomy_tables import AUTONOMY_TABLES

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    for table in AUTONOMY_TABLES:
        table.create(op.get_bind())
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table.name}" FORCE ROW LEVEL SECURITY')
            op.execute(f'''CREATE POLICY tenant_isolation ON "{table.name}"
                USING (namespace_id::text=current_setting('memory.namespace_id',true))
                WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true))''')
            # Some hosted projects have default API grants. Keep these operational
            # tables private regardless of that deployment's defaults.
            op.execute(f'REVOKE ALL ON "{table.name}" FROM PUBLIC')
            op.execute(f'''DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
                    REVOKE ALL ON "{table.name}" FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
                    REVOKE ALL ON "{table.name}" FROM authenticated;
                END IF;
            END $$''')


def downgrade():
    for table in reversed(AUTONOMY_TABLES):
        table.drop(op.get_bind())
