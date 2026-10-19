BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE deletion_tombstones (
    memory_id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (memory_id)
);

CREATE TABLE ingestion_receipts (
    namespace_id UUID NOT NULL, 
    agent_id UUID NOT NULL, 
    idempotency_key VARCHAR(128) NOT NULL, 
    request_hash VARCHAR(64) NOT NULL, 
    memory_ids JSON NOT NULL, 
    PRIMARY KEY (namespace_id, agent_id, idempotency_key)
);

CREATE TABLE memory_mutations (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    memory_id UUID NOT NULL, 
    agent_id UUID NOT NULL, 
    operation VARCHAR(40) NOT NULL, 
    revision INTEGER NOT NULL, 
    purpose VARCHAR(200) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE outbox_events (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    object_id UUID NOT NULL, 
    event_type VARCHAR(40) NOT NULL, 
    correlation_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    delivered_at TIMESTAMP WITH TIME ZONE, 
    attempts INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE users (
    id UUID NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE agents (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE namespaces (
    id UUID NOT NULL, 
    owner_id UUID NOT NULL, 
    kind VARCHAR(32) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(owner_id) REFERENCES users (id)
);

CREATE TABLE memories (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    owner_id UUID NOT NULL, 
    content_hash VARCHAR(64) NOT NULL, 
    acl_hash VARCHAR(64) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revision INTEGER NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (namespace_id, owner_id, content_hash, acl_hash), 
    FOREIGN KEY(namespace_id) REFERENCES namespaces (id), 
    FOREIGN KEY(owner_id) REFERENCES users (id)
);

CREATE INDEX ix_memories_namespace_status ON memories (namespace_id, status);

CREATE TABLE namespace_grants (
    namespace_id UUID NOT NULL, 
    agent_id UUID NOT NULL, 
    can_read BOOLEAN NOT NULL, 
    can_write BOOLEAN NOT NULL, 
    can_delete BOOLEAN NOT NULL, 
    PRIMARY KEY (namespace_id, agent_id), 
    FOREIGN KEY(namespace_id) REFERENCES namespaces (id), 
    FOREIGN KEY(agent_id) REFERENCES agents (id)
);

CREATE TABLE sessions (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    agent_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(namespace_id) REFERENCES namespaces (id), 
    FOREIGN KEY(agent_id) REFERENCES agents (id)
);

CREATE TABLE memory_embeddings (
    memory_id UUID NOT NULL, 
    model_id VARCHAR(200) NOT NULL, 
    model_version VARCHAR(100) NOT NULL, 
    dimensions INTEGER NOT NULL, 
    vector VECTOR NOT NULL, 
    PRIMARY KEY (memory_id), 
    FOREIGN KEY(memory_id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE memory_versions (
    id UUID NOT NULL, 
    memory_id UUID NOT NULL, 
    revision INTEGER NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (memory_id, revision), 
    FOREIGN KEY(memory_id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE messages (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    sequence INTEGER NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (session_id, sequence), 
    FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE provenance_edges (
    parent_id UUID NOT NULL, 
    child_id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    kind VARCHAR(32) NOT NULL, 
    PRIMARY KEY (parent_id, child_id), 
    FOREIGN KEY(child_id) REFERENCES memories (id) ON DELETE CASCADE
);

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

-- Running upgrade 0001 -> 0002

CREATE TABLE memory_lexical (
    memory_id UUID NOT NULL, 
    terms JSON NOT NULL, 
    PRIMARY KEY (memory_id), 
    FOREIGN KEY(memory_id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE entities (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    canonical_name VARCHAR(500) NOT NULL, 
    normalized_name VARCHAR(500) NOT NULL, 
    entity_type VARCHAR(40) NOT NULL, 
    resolution_confidence JSON NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (namespace_id, normalized_name), 
    FOREIGN KEY(namespace_id) REFERENCES namespaces (id)
);

CREATE TABLE entity_aliases (
    entity_id UUID NOT NULL, 
    alias VARCHAR(500) NOT NULL, 
    PRIMARY KEY (entity_id, alias), 
    FOREIGN KEY(entity_id) REFERENCES entities (id) ON DELETE CASCADE
);

CREATE TABLE entity_embeddings (
    entity_id UUID NOT NULL, 
    model_id VARCHAR(200) NOT NULL, 
    model_version VARCHAR(100) NOT NULL, 
    dimensions INTEGER NOT NULL, 
    vector VECTOR NOT NULL, 
    PRIMARY KEY (entity_id), 
    FOREIGN KEY(entity_id) REFERENCES entities (id) ON DELETE CASCADE
);

CREATE TABLE memory_entities (
    memory_id UUID NOT NULL, 
    entity_id UUID NOT NULL, 
    PRIMARY KEY (memory_id, entity_id), 
    FOREIGN KEY(memory_id) REFERENCES memories (id) ON DELETE CASCADE, 
    FOREIGN KEY(entity_id) REFERENCES entities (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

-- Running upgrade 0002 -> 0003

CREATE TABLE episodes (
    id UUID NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE episode_memories (
    episode_id UUID NOT NULL, 
    memory_id UUID NOT NULL, 
    PRIMARY KEY (episode_id, memory_id), 
    FOREIGN KEY(episode_id) REFERENCES episodes (id) ON DELETE CASCADE, 
    FOREIGN KEY(memory_id) REFERENCES memories (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002';

-- Running upgrade 0003 -> 0004

CREATE TABLE experiences (
    id UUID NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE experience_episodes (
    experience_id UUID NOT NULL, 
    episode_id UUID NOT NULL, 
    PRIMARY KEY (experience_id, episode_id), 
    FOREIGN KEY(experience_id) REFERENCES experiences (id) ON DELETE CASCADE, 
    FOREIGN KEY(episode_id) REFERENCES episodes (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0004' WHERE alembic_version.version_num = '0003';

-- Running upgrade 0004 -> 0005

CREATE TABLE graph_nodes (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    kind VARCHAR(40) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(namespace_id) REFERENCES namespaces (id)
);

CREATE TABLE graph_edges (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    source_id UUID NOT NULL, 
    target_id UUID NOT NULL, 
    relationship_type VARCHAR(40) NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (namespace_id, source_id, target_id, relationship_type), 
    FOREIGN KEY(namespace_id) REFERENCES namespaces (id), 
    FOREIGN KEY(source_id) REFERENCES graph_nodes (id) ON DELETE CASCADE, 
    FOREIGN KEY(target_id) REFERENCES graph_nodes (id) ON DELETE CASCADE
);

CREATE TABLE graph_edge_evidence (
    edge_id UUID NOT NULL, 
    memory_id UUID NOT NULL, 
    PRIMARY KEY (edge_id, memory_id), 
    FOREIGN KEY(edge_id) REFERENCES graph_edges (id) ON DELETE CASCADE, 
    FOREIGN KEY(memory_id) REFERENCES memories (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0005' WHERE alembic_version.version_num = '0004';

-- Running upgrade 0005 -> 0006

CREATE TABLE procedures (
    id UUID NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE procedure_experiences (
    procedure_id UUID NOT NULL, 
    experience_id UUID NOT NULL, 
    PRIMARY KEY (procedure_id, experience_id), 
    FOREIGN KEY(procedure_id) REFERENCES procedures (id) ON DELETE CASCADE, 
    FOREIGN KEY(experience_id) REFERENCES experiences (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0006' WHERE alembic_version.version_num = '0005';

-- Running upgrade 0006 -> 0007

CREATE TABLE goals (
    id UUID NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE goal_relations (
    parent_id UUID NOT NULL, 
    child_id UUID NOT NULL, 
    PRIMARY KEY (parent_id, child_id), 
    FOREIGN KEY(parent_id) REFERENCES goals (id) ON DELETE CASCADE, 
    FOREIGN KEY(child_id) REFERENCES goals (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0007' WHERE alembic_version.version_num = '0006';

-- Running upgrade 0007 -> 0008

CREATE TABLE insights (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    feature_hash VARCHAR(64) NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE insight_evidence (
    insight_id UUID NOT NULL, 
    episode_id UUID NOT NULL, 
    PRIMARY KEY (insight_id, episode_id), 
    FOREIGN KEY(insight_id) REFERENCES insights (id) ON DELETE CASCADE, 
    FOREIGN KEY(episode_id) REFERENCES episodes (id) ON DELETE CASCADE
);

CREATE TABLE insight_counterexamples (
    insight_id UUID NOT NULL, 
    episode_id UUID NOT NULL, 
    PRIMARY KEY (insight_id, episode_id), 
    FOREIGN KEY(insight_id) REFERENCES insights (id) ON DELETE CASCADE, 
    FOREIGN KEY(episode_id) REFERENCES episodes (id) ON DELETE CASCADE
);

CREATE TABLE episode_features (
    namespace_id UUID NOT NULL, 
    episode_id UUID NOT NULL, 
    feature_hash VARCHAR(64) NOT NULL, 
    description VARCHAR(2000) NOT NULL, 
    failure BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (episode_id, feature_hash), 
    FOREIGN KEY(episode_id) REFERENCES episodes (id) ON DELETE CASCADE
);

CREATE INDEX ix_features_namespace_key ON episode_features (namespace_id, feature_hash);

CREATE TABLE reflection_jobs (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    cursor_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id)
);

UPDATE alembic_version SET version_num='0008' WHERE alembic_version.version_num = '0007';

-- Running upgrade 0008 -> 0009

CREATE TABLE memory_clusters (
    id UUID NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE cluster_members (
    cluster_id UUID NOT NULL, 
    memory_id UUID NOT NULL, 
    PRIMARY KEY (cluster_id, memory_id), 
    FOREIGN KEY(cluster_id) REFERENCES memory_clusters (id) ON DELETE CASCADE, 
    FOREIGN KEY(memory_id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE open_loops (
    id UUID NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
);

CREATE TABLE prospective_memories (
    id UUID NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0009' WHERE alembic_version.version_num = '0008';

-- Running upgrade 0009 -> 0010

CREATE TABLE background_jobs (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    idempotency_key VARCHAR(200) NOT NULL, 
    queue VARCHAR(50) NOT NULL, 
    payload JSON NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    retry_count INTEGER NOT NULL, 
    priority INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    lease_until TIMESTAMP WITH TIME ZONE, 
    lease_token UUID, 
    last_error VARCHAR(200), 
    PRIMARY KEY (id), 
    UNIQUE (idempotency_key)
);

CREATE INDEX ix_jobs_ready ON background_jobs (status, available_at, priority);

CREATE TABLE retrieval_events (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    agent_id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE memory_access_events (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    memory_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE tenant_policies (
    namespace_id UUID NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (namespace_id), 
    FOREIGN KEY(namespace_id) REFERENCES namespaces (id)
);

UPDATE alembic_version SET version_num='0010' WHERE alembic_version.version_num = '0009';

-- Running upgrade 0010 -> 0011

ALTER TABLE "namespaces" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "namespaces" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "namespaces" USING (id::text=current_setting('memory.namespace_id',true)) WITH CHECK (id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "namespace_grants" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "namespace_grants" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "namespace_grants" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "sessions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "sessions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "sessions" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "memories" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "memories" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "memories" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "entities" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "entities" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "entities" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "memory_mutations" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "memory_mutations" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "memory_mutations" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "provenance_edges" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "provenance_edges" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "provenance_edges" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "outbox_events" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "outbox_events" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "outbox_events" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "deletion_tombstones" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "deletion_tombstones" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "deletion_tombstones" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "ingestion_receipts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "ingestion_receipts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "ingestion_receipts" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "graph_nodes" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "graph_nodes" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "graph_nodes" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "graph_edges" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "graph_edges" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "graph_edges" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "insights" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "insights" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "insights" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "episode_features" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "episode_features" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "episode_features" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "reflection_jobs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "reflection_jobs" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "reflection_jobs" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "background_jobs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "background_jobs" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "background_jobs" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "retrieval_events" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "retrieval_events" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "retrieval_events" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "memory_access_events" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "memory_access_events" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "memory_access_events" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "tenant_policies" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "tenant_policies" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "tenant_policies" USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

ALTER TABLE "memory_versions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "memory_versions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "memory_versions" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_versions"."memory_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_versions"."memory_id"));

ALTER TABLE "memory_embeddings" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "memory_embeddings" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "memory_embeddings" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_embeddings"."memory_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_embeddings"."memory_id"));

ALTER TABLE "memory_lexical" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "memory_lexical" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "memory_lexical" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_lexical"."memory_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_lexical"."memory_id"));

ALTER TABLE "memory_entities" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "memory_entities" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "memory_entities" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_entities"."memory_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_entities"."memory_id"));

ALTER TABLE "episodes" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "episodes" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "episodes" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="episodes"."id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="episodes"."id"));

ALTER TABLE "episode_memories" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "episode_memories" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "episode_memories" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="episode_memories"."episode_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="episode_memories"."episode_id"));

ALTER TABLE "experiences" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "experiences" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "experiences" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="experiences"."id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="experiences"."id"));

ALTER TABLE "experience_episodes" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "experience_episodes" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "experience_episodes" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="experience_episodes"."experience_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="experience_episodes"."experience_id"));

ALTER TABLE "procedures" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "procedures" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "procedures" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="procedures"."id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="procedures"."id"));

ALTER TABLE "procedure_experiences" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "procedure_experiences" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "procedure_experiences" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="procedure_experiences"."procedure_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="procedure_experiences"."procedure_id"));

ALTER TABLE "goals" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "goals" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "goals" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="goals"."id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="goals"."id"));

ALTER TABLE "goal_relations" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "goal_relations" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "goal_relations" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="goal_relations"."parent_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="goal_relations"."parent_id"));

ALTER TABLE "memory_clusters" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "memory_clusters" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "memory_clusters" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_clusters"."id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="memory_clusters"."id"));

ALTER TABLE "cluster_members" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "cluster_members" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "cluster_members" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="cluster_members"."cluster_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="cluster_members"."cluster_id"));

ALTER TABLE "open_loops" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "open_loops" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "open_loops" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="open_loops"."id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="open_loops"."id"));

ALTER TABLE "prospective_memories" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "prospective_memories" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "prospective_memories" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="prospective_memories"."id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="prospective_memories"."id"));

ALTER TABLE "insight_evidence" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "insight_evidence" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "insight_evidence" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="insight_evidence"."insight_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="insight_evidence"."insight_id"));

ALTER TABLE "insight_counterexamples" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "insight_counterexamples" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "insight_counterexamples" USING (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="insight_counterexamples"."insight_id")) WITH CHECK (EXISTS (SELECT 1 FROM "memories" AS p WHERE p.id="insight_counterexamples"."insight_id"));

ALTER TABLE "entity_aliases" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "entity_aliases" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "entity_aliases" USING (EXISTS (SELECT 1 FROM "entities" AS p WHERE p.id="entity_aliases"."entity_id")) WITH CHECK (EXISTS (SELECT 1 FROM "entities" AS p WHERE p.id="entity_aliases"."entity_id"));

ALTER TABLE "entity_embeddings" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "entity_embeddings" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "entity_embeddings" USING (EXISTS (SELECT 1 FROM "entities" AS p WHERE p.id="entity_embeddings"."entity_id")) WITH CHECK (EXISTS (SELECT 1 FROM "entities" AS p WHERE p.id="entity_embeddings"."entity_id"));

ALTER TABLE "graph_edge_evidence" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "graph_edge_evidence" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "graph_edge_evidence" USING (EXISTS (SELECT 1 FROM "graph_edges" AS p WHERE p.id="graph_edge_evidence"."edge_id")) WITH CHECK (EXISTS (SELECT 1 FROM "graph_edges" AS p WHERE p.id="graph_edge_evidence"."edge_id"));

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

ALTER TABLE messages FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON messages USING (EXISTS (SELECT 1 FROM sessions s WHERE s.id=messages.session_id)) WITH CHECK (EXISTS (SELECT 1 FROM sessions s WHERE s.id=messages.session_id));

UPDATE alembic_version SET version_num='0011' WHERE alembic_version.version_num = '0010';

-- Running upgrade 0011 -> 0012

CREATE TABLE raw_sources (
    id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(namespace_id) REFERENCES namespaces (id)
);

ALTER TABLE raw_sources ENABLE ROW LEVEL SECURITY;

ALTER TABLE raw_sources FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON raw_sources USING (namespace_id::text=current_setting('memory.namespace_id',true)) WITH CHECK (namespace_id::text=current_setting('memory.namespace_id',true));

UPDATE alembic_version SET version_num='0012' WHERE alembic_version.version_num = '0011';

-- Running upgrade 0012 -> 0013

CREATE INDEX ix_memory_vectors_768_hnsw ON memory_embeddings
        USING hnsw ((vector::vector(768)) vector_cosine_ops) WHERE dimensions=768;

CREATE INDEX ix_outbox_pending_namespace ON outbox_events(namespace_id,created_at) WHERE delivered_at IS NULL;

CREATE INDEX ix_jobs_namespace_ready ON background_jobs(namespace_id,status,available_at,priority);

CREATE INDEX ix_reflection_cursor_namespace ON reflection_jobs(namespace_id,cursor_time DESC);

CREATE INDEX ix_features_namespace_changed ON episode_features(namespace_id,created_at);

UPDATE alembic_version SET version_num='0013' WHERE alembic_version.version_num = '0012';

COMMIT;

