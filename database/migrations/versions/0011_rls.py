"""Force tenant isolation for application roles. Superusers still bypass PostgreSQL RLS."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

DIRECT = "namespaces namespace_grants sessions memories entities memory_mutations provenance_edges outbox_events deletion_tombstones ingestion_receipts graph_nodes graph_edges insights episode_features reflection_jobs background_jobs retrieval_events memory_access_events tenant_policies".split()
CHILD = {
    "memory_versions": ("memory_id", "memories"),
    "memory_embeddings": ("memory_id", "memories"),
    "memory_lexical": ("memory_id", "memories"),
    "memory_entities": ("memory_id", "memories"),
    "episodes": ("id", "memories"),
    "episode_memories": ("episode_id", "memories"),
    "experiences": ("id", "memories"),
    "experience_episodes": ("experience_id", "memories"),
    "procedures": ("id", "memories"),
    "procedure_experiences": ("procedure_id", "memories"),
    "goals": ("id", "memories"),
    "goal_relations": ("parent_id", "memories"),
    "memory_clusters": ("id", "memories"),
    "cluster_members": ("cluster_id", "memories"),
    "open_loops": ("id", "memories"),
    "prospective_memories": ("id", "memories"),
    "insight_evidence": ("insight_id", "memories"),
    "insight_counterexamples": ("insight_id", "memories"),
    "entity_aliases": ("entity_id", "entities"),
    "entity_embeddings": ("entity_id", "entities"),
    "graph_edge_evidence": ("edge_id", "graph_edges"),
}


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    scope = "current_setting('memory.namespace_id',true)"
    for table in DIRECT:
        column = "id" if table == "namespaces" else "namespace_id"
        predicate = f"{column}::text={scope}"
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" USING ({predicate}) WITH CHECK ({predicate})'
        )
    for table, (column, parent) in CHILD.items():
        predicate = (
            f'EXISTS (SELECT 1 FROM "{parent}" AS p WHERE p.id="{table}"."{column}")'
        )
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" USING ({predicate}) WITH CHECK ({predicate})'
        )
    predicate = "EXISTS (SELECT 1 FROM sessions s WHERE s.id=messages.session_id)"
    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE messages FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON messages USING ({predicate}) WITH CHECK ({predicate})"
    )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in DIRECT + list(CHILD) + ["messages"]:
        op.execute(f'DROP POLICY tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
