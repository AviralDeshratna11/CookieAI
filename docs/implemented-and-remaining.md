# CookieAI: implemented capabilities and remaining work

Updated 20 October 2026. This document consolidates the existing memory system
and the new continuous-autonomy implementation. It describes source code and
recorded tests, not a fresh production uptime check.

**Current position:** CookieAI has a persistent memory system, background
learning, an authenticated assistant, and an opt-in supervisor for approved,
bounded tasks. It is **not yet a complete, independently operated general
autonomous agent**. Features, tests and deployment are separate milestones.

## 1. Architecture in place

- Python/FastAPI API and a separate persistent worker.
- PostgreSQL/pgvector as canonical storage; the recorded deployment uses Supabase.
- Three logical stores: atomic memories/vectors, entities/aliases/entity vectors,
  and relational sources/sessions/jobs/outcomes/provenance.
- Redis for operational events, rate limits and progress state; SQL for durable jobs.
- Existing NVIDIA Nemotron generation and embedding configuration preserved.
- CookieAI owns authorization, retrieval, scheduling, verification, learning and
  forgetting. Optional Hermes executes through CookieAI's model/tool broker.

## 2. What is implemented

| Area | Available behavior | Important boundary |
|---|---|---|
| Persistent memory | Typed records, stable IDs, raw sources, timestamps, epistemic labels, versions, audit and provenance | Representative extraction accuracy across domains/languages is unverified |
| Ingestion | Attributed atomic extraction, source/span validation, idempotency, transactional rollback and retention controls | Generated assertions cannot certify their own truth or authority |
| Updates and forgetting | Corrections, contradictions, temporal changes, revision checks, descendant invalidation and targeted deletion | Active-store erasure does not prove deletion from providers or historical backups |
| Entities | Separate identities, aliases, vectors and memory links; conservative normalized-name matching | General same-name/pronoun ambiguity remains incomplete |
| Retrieval | Hybrid vector/lexical/entity/graph/context ranking, model-space checks, authorization and conflict visibility | Some scans/adapters and representative filtered-vector recall need work |
| Continuity | Authorized cross-session context and bounded asynchronous continuity snapshots with revision checks | Not an exhaustive lifetime autobiography |
| Assistant | Authenticated durable turns, context retrieval, configured model calls, ingestion and explicit feedback; API/CLI | A polished product UI is not delivered |
| Prompt budgets | Whole assistant/Hermes prompt accounting, tool schemas, template allowance and reserved output | Quality and usefulness under long histories still need evaluation |
| Episodes and experience | Ordered attributed attempts, observations, failures, outcomes, structural grouping and conditional experience | General complex/interleaved task segmentation is not fully evaluated |
| Reusable procedures | Observed-sequence support gates, applicability, failures, recovery, provenance and feedback | Rich parameterized branches and general procedure induction remain partial |
| Relationship discovery | Tool/configuration associations, bounded model proposals, structured recurrence/dependencies/co-mentions/time/order and analogy paths | Observational heuristics are not causality or calibrated probabilities |
| Finding state | Evidence revisions, stable identities, state history, counterevidence, expiry and invalidation | Full reviewed semantic merge/retire/supersession administration remains incomplete |
| Prospective memory | Matching, activation, acknowledgement, dismissal, snoozing, suppression and usefulness feedback | All trigger families and interruption usefulness are not proven |
| Authorization | Server-bound identity, namespaces, grants, object restrictions, operation scopes, same-user agent transfer and PostgreSQL RLS | Organization administration and cross-user federation are incomplete |
| Worker operations | Durable SQL jobs, idempotency, renewable leases, bounded retries, queue aging, maintenance schedules and progress health | Sustained operational acceptance is still required |

## 3. Newly implemented autonomous workflow

The bounded loop now implemented is:

```text
Explicitly approved task linked to a goal
  -> schedule or authorized canonical event
  -> existing durable job queue and worker
  -> authorized context and current evidence revisions
  -> procedure applicability and artifact preconditions
  -> bounded deterministic or Hermes execution
  -> independent deterministic verification
  -> attributed outcome, observations and episode
  -> eligible experience learning and later retrieval
  -> wait, repeat within approval, stop, or close an explicitly approved goal
```

| Capability | Implemented details |
|---|---|
| Durable task definition | Owner/agent/namespace, objective, immutable criteria, tool subset, priority, deadline, dependencies, parent, evidence revisions and resource limits |
| Lifecycle | Queued, running, waiting, paused, completed, failed, cancelled, exhausted and uncertain states; revision-checked controls |
| Activation | Manual, scheduled/repeating and explicitly subscribed canonical-event tasks; event deduplication/coalescing and self-trigger exclusion |
| Execution bounds | Per-run tool/model/time limits, finite runs/evaluations and durable UTC daily execution counters |
| Goal completion | Independent success can close the parent goal only when that behavior was approved; other goal tasks stop on evaluation |
| Independent checks | Decimal result, scoped text existence, SHA-256 content and exact typed JSON fields; artifact preconditions reread before action |
| Hermes controls | Separate opt-in and agent allowlist, isolated pinned runtime, parent-brokered provider/tools, exact task tool subset and model-call charging |
| Recovery | Intent/result journaling, lease fencing and uncertainty after lost execution; no blind replay of an unknown result |
| Changed conditions | Procedure revision pinning, current fingerprint conditions and artifact preconditions prevent stale execution |
| Evidence origin | REAL/SYNTHETIC/REHEARSAL separation; synthetic/rehearsal evidence cannot activate real-world procedures |
| Failure-aware context | Relevant failed actions and known exceptions accompany retrieved experience/procedures |
| Contrastive discovery | Bounded outcome cohorts produce evidence-linked candidate associations with exposure counts, limitations and counterevidence revision |
| Utility metadata | Supplied memory revisions, retrieval latency, action count and verified result; influence remains explicitly unmeasured |
| Erasure | Task contexts, journals and dependent jobs participate in forgetting and late-callback fencing; content-free quota receipts deliberately survive |
| Status/API | Task creation, owner-scoped pagination, inspection, pause/resume/cancel and progress/usage status |

Current executable tools are **bounded Decimal arithmetic** and **read-only UTF-8
`.txt` files up to 8 KiB in a provisioned per-agent workspace**. There is no
unrestricted shell, arbitrary web/service access, general file writing or
model-controlled expansion of execution authority. These limits materially
restrict which practical goals the system can currently complete.

## 4. Implemented but not deployed or fully validated

- Source migration **0019** adds task/run/usage/event state; the active hosted
  database was not migrated during the autonomy implementation.
- Optional Hermes Docker image and Compose overlay are prepared. Configuration
  validation passed; image build/start did not run because the Docker engine was
  unavailable during verification.
- The tested Hermes compatibility pin remains the earlier audited release.
  Current-release replacement and retention/security compatibility gates remain.
- Autonomy and Hermes remain disabled by default and require explicit agent
  allowlists. Code availability does not mean those services are enabled now.
- Historical PostgreSQL/Redis/live-provider reports remain historical evidence;
  they do not validate all new supervisor paths.

## 5. What is still left

| Priority | Remaining work | Completion evidence needed |
|---|---|---|
| 1 | Validate deployment plumbing on a disposable PostgreSQL/Redis stack | 0019 upgrade/downgrade, restricted-role RLS, concurrent workers/quota races, real restarts and interruption recovery |
| 2 | Expand useful task families and verifiers | Concrete scoped tools, test-command/service-health checks, bounded inputs/outputs, explicit write policies and side-effect reconciliation |
| 3 | Complete reviewed finding lifecycle and entity ambiguity | Conservative semantic deduplication/merge, retirement/supersession, history preservation and same-name/pronoun evaluations |
| 4 | Add targeted background investigation | Prioritized unresolved questions, usefulness/urgency/cost heuristics, daily limits, depth/concurrency bounds and valid no-work behavior |
| 5 | Build rehearsal curriculum and utility evaluation | Isolated held-out tasks, changed-condition cases, baseline/replay comparisons and no synthetic support inflation |
| 6 | Strengthen reusable procedures and segmentation | Typed parameters/branches, executable preconditions, broader recovery strategies, interleaved/resumed-task acceptance |
| 7 | Broaden relationship discovery | Quantitative anomalies, temporal/dependency/graph motifs, tool/environment interactions and broader analogies with false-association measurement |
| 8 | Complete prospective activation breadth | Recurring errors, changed environments, dependency/review/deadline triggers, relevance and notification usefulness/interruption measurement |
| 9 | Scale retrieval and continuity | Indexed lexical/graph adapters, remaining pagination, representative corpus/query benchmarks, filtered recall, latency/query plans and longitudinal context utility |
| 10 | Complete product/admin/modality requirements | Organization roles/revocation, validated tenant settings, consent-based federation and approved document/image/audio understanding pipelines |
| 11 | Harden continuous operations | Linux builds, queue saturation/soak, database/network outages, credential rotation, encrypted scheduled backups, isolated restore and configured alerts |
| 12 | Close requirement-level acceptance | Manual audit of the retained 108-section/1,054-clause inventory, full A-J scenario coverage, representative longitudinal results and framework comparisons |

No defensible overall completion percentage is available: the full inventory has
not passed clause-by-clause acceptance. Passing a small synthetic workflow does
not establish broad autonomous competence or show that Hermes improves quality.

## 6. Verification evidence

| Check | Recorded result | What it establishes |
|---|---|---|
| Full default regression | **139 passed, 14 skipped** | Existing behavior and bounded new fixture scenarios |
| Selected real-Hermes regression | **27 passed** | Actual isolated engine/SDK with scripted model responses, including task policy and independent verification |
| Repository Ruff lint | Passed | Selected static correctness/style rules |
| Git whitespace check | Passed | No reported whitespace errors |
| Alembic 0018-to-0019 offline SQL | Passed | Migration renders; not proof of PostgreSQL execution/RLS behavior |
| Optional Compose configuration | Passed | Configuration resolves; not proof of image build or uptime |

The default skips cover unselected Hermes runtime tests, PostgreSQL, Redis and
opt-in live-provider checks. Real-engine scripted tests are distinct from a live
model. New supervisor live-provider quality, production concurrency, actual OS
death, sustained uptime and longitudinal memory benefit remain unverified.

## 7. External decisions and dependencies

- An available Docker engine and isolated database/Redis test target for runtime
  acceptance; hosted migration is a separate deployment action.
- A hosting target for operation independent of this PC. Local continuous work
  depends on the PC, Docker, database and provider staying available.
- Backup encryption/storage and retention destinations, alert destinations and
  credential-rotation configuration.
- Approved modality providers and explicit organization/federation consent rules.

These dependencies do not block independent engineering on the investigation
scheduler, lifecycle workflows or rehearsal/evaluation harness.

## 8. Detailed references

- [Autonomy requirement/evidence ledger and next executable steps](autonomy-execution-ledger.md)
- [API, configuration, startup, tools, recovery and retention](autonomy-operations.md)
- [Machine-readable validation results](autonomy-validation-results.json)
- [Detailed existing-system status and roadmap](project-status-and-roadmap.md)
- [Architecture](../architecture.md)
- [Original requirement inventory](requirements-matrix.md)
- [Prior memory-loop acceptance](memory-loop-acceptance.md)
- [Hermes integration and historical evidence](hermes-integration.md)

The user subsequently authorized publishing repository updates to GitHub. That
publication does not authorize applying hosted migrations, enabling paid
services or deploying the application.
