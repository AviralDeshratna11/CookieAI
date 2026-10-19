BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id UUID NOT NULL, 
    PRIMARY KEY (id)
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

CREATE TABLE messages (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    sequence INTEGER NOT NULL, 
    payload JSON NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (session_id, sequence), 
    FOREIGN KEY(session_id) REFERENCES sessions (id)
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

CREATE TABLE provenance_edges (
    parent_id UUID NOT NULL, 
    child_id UUID NOT NULL, 
    namespace_id UUID NOT NULL, 
    kind VARCHAR(32) NOT NULL, 
    PRIMARY KEY (parent_id, child_id), 
    FOREIGN KEY(child_id) REFERENCES memories (id) ON DELETE CASCADE
);

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

COMMIT;

