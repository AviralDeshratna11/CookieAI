# Phase 12 operational hardening

Latest local extension: [approved continuous execution](autonomy-operations.md)
and [requirement/evidence checkpoint](autonomy-execution-ledger.md). Migration
0019 adds task/run journals, event receipts and durable execution budgets. Worker
scheduling, independent verifiers and erasure fencing are fixture-tested;
production database/container recovery acceptance remains open. Counts below
describe earlier historical gates.

Migrations 0010 and 0011 add durable jobs, retrieval/access events, tenant policies and forced PostgreSQL RLS. A non-superuser test proves default-deny and namespace isolation for memory and vector tables. Domain mutations enforce their required scopes. Derived records and cross-agent transfer preserve evidence permissions.

Migration 0012 stores raw evidence separately from the bounded rolling context. Erasure clears source-session raw content, and mutation-time lease checks prevent canceled jobs from restoring deleted input. The completion pass adds migration 0013, real embeddings, persistent discovery workers and expanded acceptance checks. The current suite has 92 passing tests on the host and in Python 3.12 Docker; see verification.md for exact scope.

Workers use SQL job leases, idempotency, bounded retry/backoff and dead jobs. Redis streams publish content-free outbox events; consumer groups acknowledge and reclaim events; dispatch schedules graph/experience/procedure projections. Execution rechecks current grants. Periodic maintenance covers reflection, consolidation, decay and DREAMER; session completion queues episodes. Working-state Redis contains IDs only. Deletion purges pending raw jobs and traverses provenance, clearing versions, vectors, graph evidence, orphan entities and summaries. Export/user deletion explicitly use the authenticated namespace.

REST adds rate limits, redacted errors, explanations and metrics. Typed YAML policy supports environment and managed tenant overrides. Twelve prompt files are versioned. AgentTools exposes sixteen identity-bound tools. Docker uses Python 3.12 and a restricted application role, separate from migration/bootstrap credentials.

Evidence includes real TCP HTTP through PostgreSQL/pgvector, real Redis, concurrent deduplication, rollback, restricted-role RLS, 100-event reflection, counterevidence, analogy, deletion, injection/data separation and concurrent HTTP smoke load. Exact results are in verification.md.

Limits: configure deployment TLS, encrypted disks/backups, secret rotation, distributed ingress rate limits and backup retention for the target host. Hash embeddings test plumbing, not semantic quality. Exact scoring/traversal needs indexed, paginated adapters and measured capacity for large stores. Smoke load is not sustained capacity certification. No production certification is claimed.
