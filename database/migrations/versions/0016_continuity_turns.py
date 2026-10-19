"""Derived continuity snapshots and durable namespace-isolated assistant turns."""

from alembic import op

from database.cognitive_tables import COGNITIVE_TABLES

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    for table in COGNITIVE_TABLES:
        table.create(op.get_bind(), checkfirst=True)
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table.name}" FORCE ROW LEVEL SECURITY')
            op.execute(f'''CREATE POLICY tenant_isolation ON "{table.name}"
                USING (namespace_id::text=current_setting('memory.namespace_id',true))
                WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true))''')


def downgrade():
    for table in reversed(COGNITIVE_TABLES):
        table.drop(op.get_bind())
