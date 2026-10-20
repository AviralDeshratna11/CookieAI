# CookieAI: project status and remaining work

**Prepared:** 20 October 2026, Asia/Calcutta  
**Implementation baseline:** commit `09cb35b` on `main`  
**Repository:** [AviralDeshratna11/CookieAI](https://github.com/AviralDeshratna11/CookieAI)

**Subsequent local implementation:** an optional isolated Hermes execution pilot,
full assistant prompt accounting and frontier-based graph edge retrieval have
been added after baseline `ba7a5f3`. See the [implementation ledger](implementation-ledger.md)
and [Hermes acceptance/operating notes](hermes-integration.md). Hermes remains
disabled by default; migration 0018 is prepared and has not been applied to the
active hosted database. The remaining requirements below still apply.
The follow-up local suite passed 122 tests with 11 skipped; a separate synthetic
live NVIDIA/Hermes smoke passed. These results do not replace the production and
requirement-level acceptance gaps below.

This document distinguishes implemented behavior, recorded verification, partial capabilities and remaining work. It is based on source inspection and existing acceptance reports, not a fresh test run or a new uptime check. The implementation baseline was pushed to GitHub; this document is a subsequent local addition.

## 1. Overall status

CookieAI is beyond Phase 1. It has a working memory backend, persistent discovery worker, authenticated assistant interface and explicit-outcome learning path.

The demonstrated core loop is:

```text
Authenticated interaction
  -> durable submitted turn
  -> authorized retrieval and reusable context
  -> Nemotron response
  -> source-validated user-memory ingestion
  -> explicit outcome/usefulness feedback
  -> background discovery and learning
  -> stored findings, experiences and conditional procedures
  -> relevant reuse in later sessions
  -> revision, invalidation, decay or deletion
```

The complete master specification remains **partially implemented and partially unverified**. The requirement inventory covers 108 sections and 1,054 clause groups. Passing tests do not establish acceptance of every clause, so there is no defensible overall completion percentage yet.

| Status | Meaning in this document |
|---|---|
| Implemented and verified | Working code has relevant regression or recorded live evidence; the claim is limited to those scenarios. |
| Partial | Useful behavior exists, but required breadth, workflows or controls remain missing. |
| Unverified | Implementation or design may exist without representative acceptance evidence. |
| External decision required | Verification depends on a hosting account, destination, consent policy or similar choice. |

## 2. Current services and models

| Component | Current implementation | Runs where |
|---|---|---|
| Canonical database | PostgreSQL 17 with pgvector | Supabase |
| Main-memory embeddings | `nvidia/nemotron-3-embed-1b`, 2048 dimensions | Direct NVIDIA API; vectors in Supabase |
| Entity embeddings | Same compatible embedding model/space | Direct NVIDIA API; separate projections in Supabase |
| Extraction and assistant generation | `nvidia/nemotron-3-ultra-550b-a55b` | Direct NVIDIA API |
| Proposals, interpretation and criticism | Nemotron Ultra, separate bounded invocations | Direct NVIDIA API |
| Query rewriting | Local rules in the active configuration | API process |
| Retrieval/ranking and persistence decisions | Python and SQL | This PC plus Supabase |
| API | FastAPI Docker service | This PC |
| Background worker | Separate persistent Docker service | This PC |
| Events, limits and progress state | Redis | Docker on this PC |
| Durable jobs and leases | SQL tables | Supabase |
| Rollback/test PostgreSQL | Retained Docker database, localhost port 55432 | This PC |
| Usable interface | CLI and Swagger/OpenAPI | This PC |

Ollama and Nomic describe earlier stages. They are not required by the current NVIDIA configuration. Generic local-provider defaults still exist for other development setups. Active Compose startup loads `.env`, `.env.supabase`, then `.env.cloud`.

Ultra does not run every API operation. Authorization, SQL storage, vector search, lexical matching, deterministic mining, queue management and most context composition are application/database operations. The embedding model creates vectors; Ultra performs language tasks. Application checks control database writes.

The requested policy is open models through free access, primarily Nemotron Ultra. No paid fallback was enabled. Developer endpoints remain subject to provider usage limits and availability; this is not unlimited free hosting.

## 3. Three-store architecture

The reference guide's three logical stores are preserved. PostgreSQL replaces the guide's SQLite relational implementation.

| Logical store | Contents | Implementation |
|---|---|---|
| Main memory | Atomic text, type, epistemic labels, metadata, validity, confidence, sources, provenance and vectors | PostgreSQL memory tables and pgvector |
| Entity memory | Entity identities, aliases, entity vectors and memory links | Separate entity tables/projections in PostgreSQL |
| Relational state | Sessions, messages, durable raw sources, versions, mutations, grants, jobs, outcomes and derived objects | PostgreSQL relational tables |

Redis complements these stores; it is not the canonical durable memory/job store. The rolling session buffer retains ten messages by default, configurable through policy. Durable raw evidence is separate, so pruning that buffer does not erase its source evidence.

## 4. Memory storage, ingestion and updates

### 4.1 Canonical storage and ingestion

Implemented and tested behavior includes:

- Typed memory schemas with stable UUIDs, ownership, namespaces, source attribution, UTC timestamps, validity, hashes and model-space metadata.
- Distinct labels for user statements, observations, verified information, inferences, hypotheses and correlations.
- CRUD, revision checks, versions, audit records and provenance links.
- Raw storage, inferred atomic extraction and historical procedural traces.
- Validation that extracted source IDs exist and source spans occur in supplied messages.
- Protection against extractor self-certification of verified facts or extractor-controlled authorization.
- Idempotent ingestion, including retries without caller-specified message IDs/timestamps.
- Transaction rollback on failed ingestion and a retention opt-out.
- Source storage independent of the rolling message buffer.

Historical procedural traces are distinct from learned reusable procedures. Storing a sequence does not validate it as a general strategy.

**Remaining:** representative extraction accuracy, multilingual/domain coverage, long multi-turn attribution and complex contradiction evaluation.

### 4.2 Entities

Separate entity vectors, aliases and memory links support entity-aware retrieval. Exact normalized-name resolution works; vector similarity alone does not permanently merge identities.

**Remaining:** ambiguous pronouns, same-name entities, proposed identity links, stronger producer-aware deduplication and representative resolution evaluation. Equal names can still refer to different real entities.

### 4.3 Dynamic and temporal memory

The mutation system supports corrections, contradictions, temporal changes, supersession and history. Dependent conclusions are invalidated when source evidence changes. Successful-use strength is separate from truth confidence.

Snapshots check source revisions. Findings can gain support or lose confidence after counterevidence. Maintenance handles decay, dormancy and expiry, including candidate expiry state.

Direct PATCH of a source with derived descendants is deliberately rejected. Use the explicit correction/mutation workflow to preserve invalidation. Derived claims must be regenerated from evidence rather than edited into unsupported conclusions.

**Remaining:** richer preference-change reasoning, evidence independence beyond event/session proxies, complete semantic finding merge/supersession administration and representative temporal-correctness evaluation.

### 4.4 Provenance and targeted forgetting

Derived objects retain evidence links; explanation/provenance APIs expose their basis. Targeted deletion removes relevant memory projections and derived descendants.

The latest implementation also cancels dependent queued/running jobs, scrubs affected raw payloads/cached assistant turns, revokes execution leases and prevents stale jobs or receipt replay from restoring erased information. Unrelated jobs survive where dependency information makes preservation safe. Operational keys are opaque, and deleted private text is not retained in audit-purpose fields.

Erasure conservatively covers affected raw sessions and assistant paraphrases. Legacy raw extraction jobs with insufficient dependency metadata can require broader cancellation. Namespace-wide deletion remains namespace-wide.

**Remaining:** historical backup/provider-snapshot retention and erasure policy, plus evidence covering external logs/storage. Active-store forgetting does not erase old backups automatically.

## 5. Hybrid retrieval and reusable context

### 5.1 Retrieval

The pipeline combines vector similarity, BM25/keyword matching, entities, graph activation, temporal/context signals, importance and recency. Goals, episodes, experiences, procedures and findings contribute where applicable.

Candidate pools are combined/deduplicated, ranked and selected with diversity/context constraints. Matching model/version/dimensions prevent incompatible vector spaces from being mixed. Authorization and validity affect retrieval, and relevant unresolved conflicts remain visible.

Migration 0014 adds a 2048-dimensional half-vector HNSW candidate index. Stored vectors and final similarity scoring retain full precision.

**Remaining:** scalable lexical/graph adapters, broader pagination, representative filtered ANN recall, diverse-query latency and capacity evaluation. An available index does not establish production recall quality.

### 5.2 Cross-session and cross-agent context

A new session can receive authorized earlier memories, projects/goals, episodes, experiences, procedures, findings, conflicts, prospective reminders and continuity snapshots. Supported cross-agent transfer intersects sender/receiver permissions.

Stored context is labeled untrusted data, with epistemic categories and provenance. It must not become a system-instruction channel. Same-user authorized agent transfer does not establish full cross-user federation or organization membership management.

### 5.3 Persistent continuity

Asynchronous extractive continuity snapshots are stored by source authorization partition. Coverage is bounded to 20 sources per partition from 200 recent authorized records.

Snapshots are reusable across sessions and validate source revisions, validity and current visibility. Stale, erased or inaccessible evidence suppresses reuse until regeneration. This provides bounded continuity, not exhaustive lifetime autobiography.

### 5.4 Context token budgets

The active setup uses a pinned public Nemotron tokenizer. Policy allocates space across recent messages, memories, continuity, episodes, experiences, procedures, findings, goals/projects and prospective content.

The stated budget covers serialized context JSON. System instructions, current-user text, chat-template overhead and output require additional allowance outside it. Without a tokenizer, the system explicitly labels its conservative UTF-8 upper-bound fallback.

**Remaining:** broader longitudinal context-usefulness evaluation, richer autobiographical coverage and full application-level prompt/output budgeting where required.

## 6. Background relationship discovery

### 6.1 What the discovery agent does

A separate worker performs scheduled/event-triggered learning outside conversation turns. It can retain supported, potentially useful findings even without an immediate action.

| Discovery path | Implemented behavior | Boundary |
|---|---|---|
| Tool/configuration associations | Tool-attempt support/counterexamples, rules and optional model review | Focused family, not every success/failure relationship |
| General model-assisted discovery | Bounded proposal, counterexample and critic calls over authorized direct evidence | Production precision unmeasured |
| Structured recurrence | Repeated subject/predicate/object observations | Exact normalized fields |
| Declared dependencies | Repeated explicit `depends_on` records | Does not prove causal dependency |
| Entity co-mentions | Repeated explicit entity pairs | Remain candidates; co-mention is not relationship proof |
| UTC windows | Explicit events in six-hour UTC windows | Candidate observations, not local-calendar forecasting |
| Adjacent event sequences | Explicit order within a bounded interval | Candidates; no invented missing events or causality |
| Structural analogy | Comparable experiences/common successful actions with counterexample checks | Conditional and bounded; broader analogy families partial |

Structured discovery scans up to 300 recent authorized sources and evaluates up to eight changed findings per pass. General discovery supplies at most 60 direct-source memories to the model from its bounded recent window, with at least three distinct supporting sessions.

Derived findings, summaries and assistant output cannot become independent support merely through new IDs. Stable producer/event identities and session checks reduce replay inflation, but do not prove statistical independence.

### 6.2 Finding lifecycle

Shared metadata supports candidate, active, disputed, rejected, dormant, invalidated, superseded and expired labels. The existence of a label does not imply a complete administrative workflow for every transition.

Findings retain stable identity, type, statement, applicability, supporting/counterexample IDs, source revisions, provenance, heuristic confidence, limitations, alternative explanations, review times and bounded state history.

Verified behavior includes stable-ID revision after counterevidence, structural lexical deduplication, conservative confidence changes, source-change invalidation, candidate expiry and replay protection. Candidates/rejected/invalidated findings are excluded from ordinary recall as appropriate.

Confidence is a heuristic, not a calibrated probability. Separate calls to the same Nemotron model do not establish independent model weights. An association is not a causal conclusion.

**Remaining:** semantic paraphrase merging, complete merge/supersession administration, broader quantitative anomaly/dependency/graph-motif miners, representative precision/false-association evaluation and empirical calibration if required.

### 6.3 Serendipity and future-use matching

Serendipity explores bounded structural, temporal and distant-domain experience neighbors with evidence and counterexample/critic checks. No supported finding is a valid result.

Prospective memory supports context/entity/event/time-style matching, activation, acknowledgment, dismissal, snoozing, utility feedback and repeat suppression. Eligible active tool/general findings with applicability information can create inferred future-use opportunities.

No external action is executed solely because a relationship/reminder was discovered.

**Remaining:** every master-required neighbor family, broader graph/analogy exploration, complete idle-compute scheduling and representative reminder usefulness/false-positive evaluation.

## 7. Episodes, experiences and procedures

Episodes preserve attributed observations, goals, tool attempts, success/failure, outcomes, timing and source IDs. Stable event identities prevent repeated delivery from simply inflating evidence.

Segmentation supports session/time/task boundaries and bounded model-assisted contiguous partitioning. Every supplied source ID must appear once in chronological order; models cannot invent actions or outcomes.

Experiences compile comparable episodes into conditional descriptions, attempted/successful/failed actions, applicability, exceptions and structural fingerprints.

Learned procedures require at least three matching observed successful action sequences, or explicit attributed confirmation through the supported path. Differently ordered successful actions are not arbitrarily combined into an allegedly observed sequence. Recovery steps require a preceding observed failure. Outcome feedback can reduce confidence.

**Remaining:** representative complex-task segmentation quality, richer sequence abstraction, broader domain coverage and stronger evaluation of generalization/source independence.

## 8. Actual assistant interface

The assistant API/CLI accepts authenticated turns, durably records retained submissions, retrieves context, generates responses, ingests user information and captures explicit feedback. Retained work can be inspected/retried after provider failure.

Assistant-generated text is attributed history, not automatically verified independent evidence. Helpful-memory feedback affects successful-use strength rather than truth confidence. Feedback receipts are idempotent and bounded.

The assistant's `retain:false` generates a non-retained response. Ingestion's `retain:false` stores no interaction and invokes no extraction; these are different API contracts.

The usable interface is a CLI/API. A polished UI and an arbitrary external tool-execution product are not delivered. Real tool/task outcomes must be supplied by the caller or integration; the assistant does not invent execution evidence.

## 9. Worker reliability and operational behavior

Implemented controls include durable SQL jobs, idempotency, renewable leases, stale-lease recovery, transactional execution checks, bounded event dispatch, a separate service agent and graceful shutdown.

Ten-minute queue aging prevents continuous fresh chat from indefinitely starving old discovery. Failures use bounded retries, quota backoff and inspectable failed state after five failed attempts. There is no paid fallback.

Default/recorded scheduling includes ten-minute reflection/continuity, hourly serendipity, daily consolidation/decay and weekly DREAMER. Configuration may alter intervals.

Status exposes queue counts, oldest pending age, actual completion times, worker stage and stall status. Health requires recent progress plus a heartbeat. Batched episode/experience/procedure/provenance reads reduce avoidable cloud round trips.

**Remaining:** sustained restart/soak tests, actual database/network interruptions, saturation recovery, distributed capacity and configured alert destinations. Local background execution requires this PC and Docker to remain available.

## 10. Security, migration and backup progress

Implemented security includes server-bound bearer identities, namespace grants, object restrictions, operation scopes, supported same-user agent sharing, RLS and a restricted database application role without superuser/RLS-bypass privileges.

Client-to-Supabase pooler TLS was verified. The new continuity/assistant tables have forced namespace RLS and no public API-role grants in the recorded review. These specific checks are not a blanket security certification.

Private environment files, credentials, dumps and local caches are Git-ignored. The public tokenizer manifest is tracked; its downloaded artifact is ignored and included in local builds when available. Secrets/private source text are not intentionally emitted in logs.

| Milestone | Recorded result |
|---|---|
| Migration 0014 | 2048-dimensional half-vector candidate index |
| Migration 0015 | Explicit job dependency metadata |
| Migration 0016 | Persistent continuity/assistant tables and RLS |
| Migration 0017 | Job start/finish progress fields |
| Hosted 0014 to 0017 upgrade | Backup first, transactional upgrade, all 125 original canonical IDs retained with matching digest |
| Later hosted backup restore | 126 canonical records restored into a fresh local database; temporary destination removed |

These counts are different snapshots: a newly generated continuity record explains the later increase. They are not a claim that the live count will remain fixed. The drill covers the application's public schema, not managed Supabase Auth/Storage.

Dumps remain unencrypted and unscheduled. A previous-source rollback image is retained as `cookieai-runtime:before-memory-loop`. Supabase advisory checks were unavailable because the connected account returned permission denied; direct SQL checks passed, but the advisory review remains unavailable.

**Remaining:** managed secrets/rotation, encrypted scheduled off-host backups, retention/deletion policy, monitored restore drills, operational alerting and deployment-specific HTTPS/storage controls.

## 11. What has actually been tested

| Check | Recorded result | Limit |
|---|---|---|
| Linux Python 3.12 regression | 121 passed; one intentional live-provider skip | Isolated fixtures are not production accuracy evidence |
| Windows Python 3.11 regression | 120 passed before final HTTP-contract fixture | Do not report 121 Windows tests as verified |
| Separate real NVIDIA acceptance | Passed in 155.85 seconds | Small labeled synthetic scenario |
| Hosted API/context recall | HTTP 200, relevant context | Point-in-time result |
| Context budget | 7,082/8,000 model tokens | Context JSON only |
| Cold context assembly | 18.828 seconds | One measurement, not p95/capacity |
| Hosted upgrade | 125 IDs, matching digest | Upgrade-window snapshot |
| Hosted restore | Passed, 126 records | Local isolated destination; unencrypted dump |
| Worker | Healthy, useful jobs completed, no pending backlog in final check | Not 24/7 availability evidence |
| Ruff, formatting, whitespace | Passed | Static checks do not replace behavior tests |
| Known warning | Starlette/httpx test-client deprecation | Compatible dependency update remains |

The real-provider test extracted a project fact, recalled it in a new assistant session, recorded three explicit synthetic successful outcomes, compiled an ordered procedure, built continuity and supplied the procedure to a later assistant turn. It used an isolated local PostgreSQL schema and did not drain the live user's queue.

Regression coverage also exercises finding revision/counterevidence, candidate isolation, corrections, deletion during generation, source attribution, cross-agent restrictions, stale leases, quota backoff and recovery after a simulated provider interruption.

These results do not establish the master latency target, production relation precision, general entity/temporal accuracy, large-corpus ANN recall or sustained outage recovery.

## 12. Remaining work in priority order

| Priority | Remaining work | Evidence required to close it | Dependency |
|---|---|---|---|
| P0 | Requirement-level audit | Every applicable clause mapped to current code, acceptance and status; stale summaries reconciled | Engineering review |
| P1 | Retrieval/context performance | Representative corpus sizes, diverse queries, cold/warm distributions, plans and filtered ANN recall | Corpus/benchmark design |
| P1 | Discovery quality | Labeled positive/negative cases, precision, false associations, counterevidence recovery and valid no-finding behavior | Domain data |
| P1 | Finding lifecycle breadth | Semantic dedup and reviewed merge/supersession/retirement preserving provenance/audit | Engineering/tests |
| P1 | Sustained reliability | API/worker restarts, quotas/timeouts, database loss and queue pressure without lost observations/stale commits | Controlled failure environment |
| P1 | Encrypted operational backups | Scheduled encrypted off-host copies, retention, alerts and successful isolated restores | Destination, key ownership and policy |
| P1 | Managed secrets/monitoring | Credential rotation and tested failure/lag alerts to real recipients | Selected services/destinations |
| P2 | Broader deterministic discovery | Quantitative anomaly/dependency miners and fuller event/graph motifs with support/counterexample rules | Engineering/labeled examples |
| P2 | Entity ambiguity | Same-name/pronoun cases resolved or explicitly uncertain; reviewed identity updates | Resolution dataset |
| P2 | Richer learning | Complex segmentation and conditional sequences evaluated across successes/failures | Task/outcome data |
| P2 | Serendipity coverage | Remaining neighbor families, bounded fair exploration and measured usefulness | Engineering/feedback data |
| P2 | Richer continuity | Longer-range identity/project history useful within ACL/token limits | Longitudinal data |
| P2 | Tenant policy completeness | Supported/unsupported overrides, administration and isolation tests | Admin workflow design |
| P2 | Organizations/admin policy | Membership lifecycle, role changes/revocation and tenant boundaries | Role/policy decisions |
| P2 | Cross-user federation | Consent, sharing/revocation, export/deletion and provenance boundaries | Consent/product policy |
| P2 | Required modalities | Real image/audio/document processing and suitable embedding/retrieval, not artifact links alone | Modality services/evaluation |
| Conditional | Hosting independent of PC | Supported persistent worker/API/Redis hosting and recovery | Hosting account/target |
| Conditional | Public HTTPS/hardening | Verified ingress TLS, access/rate controls and storage/retention controls | Public deployment decision |
| Optional product layer | Polished UI/external action integrations | Usable interfaces, explicit authorization and actual outcome capture | Separate product scope |

These priorities are recommended order, not effort estimates. Enterprise/modality requirements remain applicable master requirements; the optional interface layer is distinguished from them.

External controls can be prepared locally, but require actual account/destination/policy choices for complete verification. The selected runtime target remains Docker on this PC, with no claim of always-on availability independent of it.

## 13. Using the system now

Open `http://127.0.0.1:8010/docs` for Swagger. In PowerShell at the repository root:

```powershell
.venv\Scripts\python.exe -m apps.cli.chat
```

For a cross-session test, use separate invocations:

```powershell
.venv\Scripts\python.exe -m apps.cli.chat --message "Remember that Project Cedar uses PostgreSQL."
.venv\Scripts\python.exe -m apps.cli.chat --message "Which database does Project Cedar use?"
```

Each invocation defaults to a new session. For continuing one session, generate a UUID with `[guid]::NewGuid().ToString()` and reuse it through `--session <UUID>`. A new session can still retrieve authorized persistent memory from previous sessions.

Current hosted-backed startup:

```powershell
docker compose --env-file .env --env-file .env.supabase --env-file .env.cloud -f docker-compose.yml -f docker-compose.hosted.yml up -d api worker
```

This assumes provisioning, private configuration, tokenizer and migrations already exist; it is not a fresh-machine bootstrap. See [running locally](running-locally.md) and [migration/rollback boundaries](memory-loop-acceptance.md). Do not rerun the original local-to-hosted copy against the populated active database.

| Purpose | API examples |
|---|---|
| Assistant/outcomes | `POST /v1/agent/turn`, `GET /v1/agent/turn/{turn_id}`, turn feedback |
| Ingestion/recall | `/v1/memory/remember`, `/v1/memory/search`, memory CRUD |
| Correction | `/v1/memory/mutate`, `/v1/memory/{memory_id}/correct` |
| Context/continuity | `/v1/context/build`, `/v1/context/transfer`, `/v1/context/continuity`, `/v1/context/refresh` |
| Discovery | `/v1/insights`, `/v1/reflection/run`, `/v1/serendipity/run` |
| Learning | Episode APIs, experience/procedure compile/search, procedure feedback |
| Future-use matching | Prospective memory creation, activation and feedback |
| Operations | `/v1/operations/status`, `/v1/jobs`, failed-job retry, `/health/live` |
| Evidence/forgetting | Provenance, explanation, memory deletion and authorized namespace export/deletion |

Swagger provides exact methods/schemas. Protected requests use a bearer credential plus session/purpose headers. Never copy real credentials into shared examples.

## 14. Code and evidence map

| Area | Main implementation | Evidence entry points |
|---|---|---|
| Canonical memory/mutation | `memory/service.py`, `memory/mutation/`, repository | Foundation/temporal/mutation tests |
| Retrieval/entities/graph | `memory/retrieval/`, `memory/entities/`, `memory/graph/` | Hybrid/graph/PostgreSQL tests |
| Findings | `memory/insights/lifecycle.py`, `memory/reflection/` | General-revision/structured-discovery tests |
| Context/continuity | `memory/context/` | Continuity/transfer/budget tests |
| Assistant | `memory/agent/service.py`, CLI, FastAPI | Assistant-loop/API tests and live report |
| Learning | Episodes/experiences/procedures services | Episode/experience/procedure tests |
| Future opportunities | Serendipity/prospective services | Serendipity/prospective-feedback tests |
| Reliability/erasure | `workers/`, `apps/worker/`, repository | Queue-recovery/targeted-erasure/interruption tests |
| Operations | Hosted upgrade/backup scripts | Upgrade/security/restore reports |

Recorded evidence:

- [Memory-loop acceptance and boundaries](memory-loop-acceptance.md).
- [Regression results](memory-loop-regression-results.json).
- [Real NVIDIA assistant/outcome/procedure acceptance](assistant-live-results.json).
- [Final runtime context and worker progress](final-runtime-results.json).
- [Hosted migration/identity preservation](runtime-upgrade-results.json).
- [TLS, restricted role, grants and RLS](runtime-security-results.json).
- [Hosted backup/restore drill](hosted-backup-results.json).
- [Execution checklist](execution-checklist.md).
- [Original requirement inventory](requirements-matrix.md).
- [OpenAPI snapshot](openapi.json).

Older README/architecture/status passages contain historical Nomic/Ollama settings, earlier test totals and pre-tokenizer limitations. Use this dated snapshot and current reports for present status. Some requirement-matrix summaries are stale/unverified and require the P0 audit; they have not been silently promoted to complete.

## 15. What completion still means

Preserve the demonstrated core loop while closing quality, performance and reliability gaps with reproducible evidence.

Full master completion additionally requires reconciliation of every applicable clause, implementation of missing behavior, representative acceptance, required enterprise/modality workflows and deployment-appropriate operational controls. Account-dependent items need explicit destinations/policies before certification.

The current project is an **implemented and tested core memory/discovery/assistant system with an explicit advanced-feature and production-readiness backlog**.
