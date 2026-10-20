# Continuous autonomy implementation ledger

Publication follow-up: the user subsequently requested a consolidated
[implemented/remaining overview](implemented-and-remaining.md) and authorized
pushing repository updates to GitHub. Earlier no-push statements below record
the boundary of the implementation request; hosted migration/deployment remain
outside this publication action.

Request received 20 October 2026, Asia/Calcutta. Starting commit `29c5d08`;
working tree clean. Fresh default regression: 120 passed, 13 skipped (the two
optional Hermes engine tests require runtime paths). Prior evidence remains in
the implementation ledger and requirement matrix. No specification clause is
promoted merely because a related subsystem exists.

| Gate | Required behavior / planned implementation | Current status | Evidence and residual gate |
|---|---|---|---|
| 1 | Baseline and original requirement/evidence audit | Partial | Full manual clause review; original separate controlling source still unavailable |
| 2 | Durable approved tasks linked to goals, leases, schedules, budgets, dependencies, pause/cancel and verifiers | Implemented and fixture-verified for bounded read-only tasks | `test_autonomy.py`; production PostgreSQL/concurrency/restart drills remain |
| 3 | Hermes runtime and container integration, immutable per-task tool policy | Engine verified; packaging unverified | Real pinned engine/scripted provider supervisor test; Compose config passed; daemon unavailable for builds |
| 4 | Typed observations, verifier outcomes and conditional procedures | Implemented in bounded family | Failed attempt then independently verified recovery; pinned procedures and changed environment/artifact rejection; generic induction remains partial |
| 5 | Failure-first and contrastive retrieval | Implemented and fixture-verified | Failure cautions, bounded contrastive cohorts, candidate exclusion, counterevidence revision and erasure; representative quality unverified |
| 6 | Finding lifecycle and ambiguous entities | Partial | Reviewed merge/retire/revalidate and ambiguity evaluation |
| 7 | Event-triggered memory and targeted investigation | Event tasks implemented; investigation incomplete | Authorized canonical subscriptions, deduplication and loop exclusion tested; utility/interruption measurement and investigation scheduler remain |
| 8 | Rehearsal and memory utility | Partial | Synthetic/rehearsal origin separation and activation guards tested; supplied-context/cost/outcome recorded; held-out curriculum and causal utility evaluation remain |
| 9 | Retrieval, continuity, modalities and administration | Partial | Representative performance, longitudinal utility and scoped product acceptance |
| 10 | Continuous operation and recovery | Partial | Real database/Redis/service failure drills, backups and operational destinations |
| 11 | Complete A–J scenarios from the request | Unverified breadth | Fixture, real-engine, live-provider and longitudinal results separately identified |

Architecture constraints: PostgreSQL remains canonical; Redis is operational;
CookieAI owns policy and learning; model content cannot change authority or
success criteria. Initial new execution capabilities remain bounded. Existing
assistant behavior must remain available. No hosted migration, paid service,
public deployment or GitHub push is authorized by this request alone.

## Concrete checkpoint

Implemented locally after `29c5d08`:

- Migration 0019, task/run/usage/event schemas and typed contracts.
- Existing worker/queue integration, REST creation/list/status/control, scheduled
  and canonical-event activation, dependency waiting and goal closure.
- Immutable approval criteria, original-approver grants, scoped tool subsets,
  run leases, before/after guards, revision invalidation and pause/cancel fencing.
- Daily durable execution counters, bounded retries/evaluations, lost-run
  uncertainty without blind replay, and revoked-approval starvation prevention.
- Independent decimal/existence/hash/typed-JSON checks; precondition rereads.
- Sanitized actual observations, attributed episodes, REAL/SYNTHETIC/REHEARSAL
  separation, failure cautions and bounded contrastive candidate discovery.
- Required-procedure revision and condition gates; supplied-memory utility
  metadata that makes no causal claim and does not change truth confidence.
- Optional isolated Hermes image/Compose overlay and
  [operating/API/recovery notes](autonomy-operations.md).

Fresh default regression: **139 passed, 14 skipped**, 8.41 seconds. This includes
19 new passing tests; a twentieth new test requires the optional real Hermes
runtime. Existing skips include PostgreSQL/live-provider checks and optional
runtime selection. One existing Starlette/httpx deprecation warning remains.
Repository-wide Ruff lint passed. Offline Alembic `0018:0019 --sql` rendering and
Compose overlay `config --quiet` passed. Neither executes a migration or image.
The selected real-engine suite result is recorded in
[autonomy validation results](autonomy-validation-results.json).

An initial shell invocation selected system Python without project dependencies;
it failed at import and was rerun with `.venv/Scripts/python.exe`. No installation
or environment replacement was needed. A focused lint check caught a missing
import before the full regression; it was corrected and procedure execution now
has explicit matching/changed-condition coverage. No unresolved local test
failure is being hidden by these corrected checks.

## Request section coverage

| Request section | State | Remaining acceptance / implementation |
|---|---|---|
| 1 Baseline | Partial | Current repository/evidence inspected; original separate controlling source still absent; 1,054-clause manual audit incomplete |
| 2 Observable loop | Partial | Bounded A-J evidence below; representative autonomous knowledge-use loop not certified |
| 3 Ownership | Implemented within new scope | PostgreSQL remains canonical, Hermes brokered, provider configuration preserved; runtime isolation not a hostile-code sandbox |
| 4 Supervisor | Implemented in bounded family | No model-driven task expansion or automatic uncertainty investigation; approved definitions control work |
| 5 Verifiers | Partial | Four deterministic contracts implemented; test commands, HTTP health and broader schemas not implemented |
| 6 Hermes | Partial / externally dependent | Old pin retained; latest release researched; Linux build, current-release upgrade audit and deployment acceptance pending |
| 7 Capture | Partial | Actual ordered sanitized attempts/verdicts recorded; general interleaved segmentation and richer environmental capture remain |
| 8 Procedures | Partial | Existing observed-sequence gates plus origin/revision/condition checks; typed reusable branches, parameterized skill induction and full lifecycle remain |
| 9 Failure/contrast | Implemented in bounded family | Context cautions and contrasting outcome cohorts tested; ranking/applicability quality needs representative evaluation |
| 10 Discovery | Partial | New bounded contrastive family; remaining quantitative, temporal, graph and analogy breadth retained in original ledger |
| 11 Lifecycle/entities | Partial | Existing finding metadata plus contrastive revision/invalidation; reviewed semantic merges/retirement and ambiguity acceptance remain |
| 12 Prospective events | Partial | Approved canonical-event task wakeups added to existing reminders; broader trigger coverage and interruption utility evaluation remain |
| 13 Investigation | Remaining engineering | Useful unresolved-question prioritizer, daily investigation cost controls and depth policy not completed |
| 14 Rehearsal | Partial | Separate origin and no-real-promotion guards; held-out curriculum selection/evaluation not implemented |
| 15 Utility | Partial | Supplied revisions, verified outcomes and retrieval latency recorded; causal influence unknown, controlled baseline comparison pending |
| 16 Scale/modalities | Partial / externally dependent | Existing prompt budgets preserved; representative retrieval scaling and approved modality-provider pipelines remain |
| 17 Administration | Partial / policy dependent | Existing ACLs preserved; organization membership, complete tenant settings and consent-based cross-user federation remain |
| 18 Operations | Partial / externally dependent | Progress status and existing supervised worker integrated; actual restarts, PG/Redis outages, Linux builds, backups, alerts and hosting evidence remain |
| 19 Retention | Implemented/tested within new active-store scope | Tasks/journals participate in erasure; quota IDs intentionally survive; abrupt OS death/provider logs/backups not certified |
| 20 Scenarios | Partial | See scenario evidence below; no longitudinal or head-to-head framework advantage claim |
| 21 Staged gates | In progress | Existing default suite passes; later gates have not been relabeled complete |
| 22 Delivery | Local checkpoint | Code, migration, contracts, tests and notes prepared; no publication/deployment or hosted migration performed |

## Scenario evidence, with boundaries

| Scenario | Evidence now | Boundary |
|---|---|---|
| A Goal completion | Actual worker schedules fixture, verifies result; explicitly approved goal closes and other tasks stop | Deterministic fixtures, not representative production autonomy |
| B Recovery | Actual calculator division failure then approved recovery, independent expected-result check, attributed journal/episode | Synthetic controlled arithmetic, no production incident claim |
| C Later reuse | Existing real-engine scripted learning tests; new procedure-pinned supervisor accepts matching conditions | Fixture evidence; utility/causal benefit not established |
| D Changed conditions | Artifact content change prevents tool execution; procedure environment change waits | Bounded typed conditions, not universal natural-language applicability |
| E Relationship revision | Outcome contrast candidate loses support after counterevidence; stable identity invalidated; source erasure cascades | REAL-labeled fixtures, observational candidates, not discovered production truth |
| F Activation | Canonical subscribed event wakes approved task once; forged event cannot; generated sources excluded | Notification usefulness and all event families unmeasured |
| G Interruption | Simulated process interruption after durable intent, expired lease, scheduler reconciliation gives UNCERTAIN without replay | No actual OS/host/database failure drill this pass |
| H Forgetting | Evidence/task removal during execution fences late persistence and erases task/run dependents | Active-store scope; not provider/backup erasure |
| I Exhaustion | Daily tool cap stops later task even after deleting first task; finite waiting evaluations | No production saturation/concurrent multiworker quota drill |
| J Uncertainty | Failed/missing successful receipts yield inconclusive verification; candidates stay out of active recall | No broad abstention calibration claim |

## Next executable steps and concrete dependencies

1. Start an available Docker Desktop engine, build the optional image and run a
   disposable PostgreSQL/Redis stack. Exercise 0019 upgrade/downgrade and RLS as
   a restricted application role, concurrent workers, actual restarts and quota
   races. Docker engine was unavailable even outside the sandbox in this pass.
2. Run new supervisor live-provider checks only against isolated synthetic data;
   existing historical live reports do not certify new paths. Compare latency,
   verified success and provider calls against the bounded deterministic executor
   and default assistant before crediting Hermes with quality improvements.
3. Complete reviewed finding lifecycle/entity ambiguity, a bounded investigation
   prioritizer and held-out rehearsal/utility harness. These are engineering work,
   not blocked merely by an unavailable hosting target.
4. Continue original requirement-level audit, representative retrieval/continuity
   evaluation, modality providers and organization/tenant administration.
5. Obtain deployment-specific backup encryption destination, retention/alert
   destinations, federation consent rules and hosting choice only where required;
   validate isolated restore/rotation and longitudinal acceptance before any
   continuous-production claim. No such policies were invented or enabled here.

The broad request remains unfinished. This checkpoint records useful executable
progress and the next gates; it is not completion of all 22 sections or the master
specification, and it does not authorize a GitHub push or hosted migration.
