# Personal AI implementation and acceptance

Prepared 23 October 2026 (Asia/Calcutta). This document covers this implementation,
not a certification of the entire historical master specification.

## Baseline audit

The initial working tree had user changes in README.md and an untracked
docs/teammate-setup-from-scratch.md. Those changes are preserved.
The starting test run was **139 passed, 14 skipped**. Optional Hermes runtime,
PostgreSQL/live-provider tests were not silently counted as passing.

The implementation was compared against architecture.md, the implementation
ledger, memory-loop acceptance, autonomy ledger/operations, Hermes integration,
project status, and implemented/remaining reports. Code inspection confirmed:

| Requirement | Existing implementation | Initial evidence | Work in this change |
|---|---|---|---|
| Persistent memory and context | Canonical PostgreSQL, vectors, entities, revision/provenance machinery | Existing tests; real-provider history has separate limits | Preserved; adds conservative disclosure metadata |
| Approved tasks | SQL tasks/runs, approvals, schedules, leases, budgets | Bounded arithmetic/read fixtures | Extends existing task family to handoff artifacts |
| Hermes execution | Isolated pinned pilot, brokered inference | Optional engine tests; old compatibility pin | Preserved; unrestricted writes are not enabled in Hermes |
| Real artifacts | Missing from the bounded pilot | No artifact-write acceptance | New typed CookieAI-owned handoff operation |
| Procedures | Evidence-gated compiler and contextual matching | Existing procedure tests | Confirmed executable contract stored in the same procedure payload |
| Cross-project transfer | Partial structural matching | No representative semantic benchmark | Deterministic parameter/applicability checks, exceptions and revision checks |
| Corrections and erasure | Descendant invalidation, source/turn erasure | Existing tests | Local disclosure inheritance and workspace file erasure |
| Disclosure | Provider routing, no complete local-only boundary | Inspection | Shared provider enforcement; persistent namespace choices; applies to embeddings |
| Nebius | NVIDIA direct endpoint in documented configured deployment | No Nebius runtime evidence | Configuration and discovery/inference preflight; live call deferred by user |
| Mobile interface | No product frontend | Inspection | Buildless same-origin responsive portal served by FastAPI |
| Continuous hosting | Local API/worker, hosted database | Historical reports only | Hardened opt-in Compose overlay; daemon unavailable here |
| OS sandbox | Broker checks, not hostile-code isolation | Historical explicit boundary | OpenShell policy template; deployment enforcement remains unverified |

## Architecture

Phone/browser → same-origin FastAPI portal → existing task supervisor → SQL queue
and worker → bounded handoff operation → versioned artifact → independent checks
→ outcome memory/episode → existing experience/procedure compiler.

The model-assisted handoff path calls the existing compatible provider with
selected source quotations and reference IDs. It classifies references into
five sections. CookieAI renders the artifact; a model cannot introduce arbitrary
text, code, output paths, or tool authority through that response.

Sources are canonical memories plus administrator-controlled workspace text
projections under `<workspace>/<namespace>/<agent>/inputs/<source UUID>.txt`.
Outputs use `outputs/<run UUID>.json`; artifact JSON includes readable Markdown.
The project name is a label, not an authorization boundary. Actual project ACLs
come from server-bound credential project IDs and memory restrictions.

The five sections are summary, decisions, deadlines, questions, and next actions.
Missing information is explicitly unknown. Extractive mode recognizes explicit
Decision:, Deadline:, Question:, Next: prefixes. Model-assisted mode permits more
flexible categorization but still requires exact supplied evidence references.
Neither mode independently establishes the truth of a source claim.

## Run the isolated local demo

```powershell
.\.venv\Scripts\python.exe -m scripts.personal_demo
```

Open http://127.0.0.1:8765 and use `cookieai-local-demo-only`.
This known token belongs ONLY to the ephemeral loopback synthetic demo. Never
use it for public or personal-data deployment.

The command ignores private .env files, creates an isolated temporary SQLite
database, seeds three synthetic notes and a goal, and starts a bounded worker.
Choose sources, approve an extractive handoff, then inspect Tasks & results.
Use Refresh to inspect worker progress. The demo is deleted on a clean shutdown.

Hash-test embeddings and an empty test extractor are explicit test doubles.
Cloud calls are disabled. Chat generation is therefore unavailable. No synthetic
procedure is activated as real experience, and the demo starts without learned
skills. Real learning needs real verified runs and the existing compiler gates.
The demo does not establish semantic memory quality, NVIDIA integration or uptime.

### Test from a phone on the same Wi-Fi

Start the synthetic demo with `python -m scripts.personal_demo --lan`.
On Windows run `ipconfig`, find the Wi-Fi adapter's IPv4 address, and open
`http://<that-address>:8765` in the phone browser. Use
`cookieai-local-demo-only` as the access token. If Windows asks about firewall
access, allow the Python application on Private networks only. Stop with Ctrl+C.
The default command without --lan remains loopback-only.

Use a trusted local network and synthetic data: this demo uses HTTP and a known
demo token. Do not port-forward it or use it as a public deployment. Guest Wi-Fi
client isolation or a VPN may prevent phone-to-PC connections. The frontend has
a cryptographic UUID fallback for local HTTP browsers without randomUUID.

On the phone, select the Cedar note and the seeded goal, use extractive mode,
approve a task, then open Tasks & results and Refresh until it completes. Inspect
the artifact and receipt. Chat generation remains unavailable in the isolated
demo because hosted inference is disabled.

## Endpoints

### This PC: Docker portal on the same Wi-Fi

The configured hosted stack now includes the mobile portal. On your phone,
open `http://172.17.107.248:8010` while connected to the same Wi-Fi as this PC.
Connect with `MEMORY_LOCAL_TEST_TOKEN` from the private `.env` file. Keep the
PC awake and Docker Desktop running.

The private `.env.phone` stores the Wi-Fi bind address and existing portal
agent IDs. The phone overlay enables bounded approved tasks for those agents;
API and worker share the persistent personal workspace volume. PostgreSQL and
Redis remain bound to loopback. The Windows firewall rule `CookieAI phone Wi-Fi`
allows TCP 8010 on Wi-Fi only from the local subnet. This is local HTTP access;
use it on a trusted network. Campus Wi-Fi client isolation can still prevent
phone-to-PC access.

Restart this deployment after Docker Desktop starts:

```powershell
docker compose --env-file .env --env-file .env.supabase --env-file .env.cloud --env-file .env.phone -f docker-compose.yml -f docker-compose.hosted.yml -f docker-compose.personal.yml -f docker-compose.phone.yml up -d --no-deps redis api worker
```

Migration 0020 and the restricted runtime role grants were applied after a hosted
backup and successful restore drill to a disposable local database (143 canonical
records). The restart command assumes that migration is already applied. Future
schema updates still need their own backup/migration review. If Wi-Fi changes,
update the address in `.env.phone`, update the scoped firewall rule, and recreate
the API with the command above. Do not use `down -v` to restart.

All data endpoints use the existing bearer, X-Session-ID and X-Purpose headers.
Only static HTML/CSS/JS are unauthenticated; they contain no credentials.

| Endpoint | Purpose |
|---|---|
| GET /v1/portal/config | Nonsecret runtime/demo capabilities |
| GET/POST /v1/portal/sources | List visible sources / register an approved bounded note |
| GET /v1/portal/skills | Inspect existing procedures and contracts |
| POST /v1/portal/skills/{id}/confirm | Explicitly specialize an observed handoff procedure |
| POST /v1/portal/briefs/check | Evaluate skill applicability without execution |
| POST /v1/portal/briefs | Approve a durable handoff task |
| GET /v1/portal/tasks/{task}/artifacts/{run} | Authorized, integrity-checked artifact |
| GET/PUT /v1/privacy | Inspect/change namespace disclosure with revision checks |

The portal reuses existing goals, turns, task control, memory mutation and deletion
endpoints. A brief requires an existing authorized goal; task approval preserves
the same idempotency, source revisions, schedule, run budget, cancellation and
lease rules as other supervisor work. Receipt history is bounded to the existing
ten most recent runs per task through the current task API.

## Skill lifecycle and limits

Existing observed successful sequences compile into canonical procedures only
after the original evidence gates. Synthetic and rehearsal episodes remain
ineligible for real learned procedures. An attributed explicit-confirmation path
already exists in that compiler and remains unchanged.

An executable `HandoffSkill` contract then requires a separate explicit user
confirmation. It supports output format, minimum sources, required source fields,
declared exceptions, one typed tool, and the HANDOFF verifier. It has no arbitrary
code, network commands, or permission-expanding parameter substitutions.

Task parameters bind current source IDs/hashes and project label. Eligibility is
checked before approval, before execution, and at execution guards. Source and
procedure revisions are pinned. Changed or inaccessible evidence requires review.
Receipts retain the chosen skill revision and applicability result.

This is one bounded parameterized skill family, not general autonomous skill
induction. A contract can be mechanically applicable and still be a poor human
choice. Broader semantic applicability and held-out live-model evaluation remain
unverified. Synthetic fixture evaluation is not production learning evidence.

## Privacy and data control

Every compatible provider operation passes through one disclosure check,
including generation, embeddings, query rewriting, extraction and reflection.
Decorated domain services and worker dispatch carry authenticated namespace
context; calls recheck the persisted namespace choice before each request.

A new source can be LOCAL_ONLY. Its first embedding call is protected before
the source is persisted. Derived canonical memories inherit that restriction.
Mutations preserve an existing source's local-only restriction.

Conservatively, ANY retained local-only memory blocks hosted model operations
for the entire namespace. This includes superseded records. The UI explains this
behavior. It does not promise fine-grained redaction of mixed-sensitivity context.
Use separate namespaces if you need separate cloud disclosure boundaries.

Existing records default to APPROVED_CLOUD for backward compatibility. Existing
configured provider behavior remains unchanged until the operator/user chooses
local-only. No promise is made that historical data has never left the system.

Local providers require an exact operator-configured MEMORY_LOCAL_PROVIDER_URLS
entry. No URL substring heuristic declares a service local. The administrator
must verify that a configured endpoint really meets the intended trust boundary.
If no compatible local provider exists, restricted inference fails before network
transmission. Saving local-only notes also requires a compatible local embedder;
the test hash embedder is not a production semantic substitute.

Hosted handoff calls send selected quotations, reference IDs and classification
instructions. Other memory operations may send other authorized information to
configured generation/embedding providers. Handoff disclosure receipts describe
the handoff call, not every historical/background call in the namespace.
Provider-wide per-call disclosure reporting remains a follow-up; enforcement is
shared. Cost remains unknown unless trustworthy provider pricing is supplied.

Forgetting removes canonical dependent records and corresponding source/output
workspace files. OS deletion errors abort the canonical delete. Filesystem and
SQL changes cannot be one crash-atomic transaction: partial erasure can reduce
availability, and abrupt host failure requires reconciliation. Backups/provider
logs have separate retention. Access to the workspace must be limited to the
application/operator; portable path checks are not protection against an
adversarial process racing filesystem changes.

Source and output publication also recheck canonical authority while holding the
same PostgreSQL namespace lock used by erasure and cancellation. This prevents a
normal background publisher from recreating files after a completed erasure.
SQLite fixture checks do not establish PostgreSQL concurrency behavior; perform
the real concurrent erasure/publication drill on the deployment target.

## Deploy existing architecture safely

Do not change the live hosted deployment until migration and configuration are
reviewed against the intended database. The new migration is **0020**.

1. Back up the intended database and verify a restore on a disposable target.
2. Stop writers for the migration window.
3. Review `alembic upgrade 0019:0020 --sql` and apply pending migrations to the
   intended target with the migration identity.
4. Grant the restricted application/worker roles SELECT/INSERT/UPDATE on
   namespace_disclosure as required. PUBLIC/anon/authenticated grants remain
   revoked. Do not give runtime roles RLS bypass.
5. Configure API and worker consistently: handoff enabled, existing autonomy
   enabled/agent allowlist, shared workspace, selected provider and privacy.
6. Build/start with the opt-in docker-compose.personal.yml overlay, using the
   existing hosted/local database overlay appropriate to your deployment.
7. Keep API behind authenticated HTTPS ingress. The base Compose port remains
   loopback-bound; do not expose databases or Redis to phone clients.
8. Verify a real task, reboot/retry/revocation behavior, artifact persistence,
   encrypted backups and resource limits on the actual target.

The personal overlay adds a shared workspace, read-only container root, limited
tmpfs, dropped capabilities and no-new-privileges. These are useful hardening,
not an OpenShell certification or complete network egress policy.

config/openshell-handoff.yaml is a fail-closed Linux policy STARTING TEMPLATE.
The current broker launches Hermes locally; this change does not silently route
it into OpenShell. Wire the reviewed image/broker paths on the chosen supported
Linux runtime and prove blocked filesystem/network attempts before claiming OS
sandbox enforcement. No OpenShell/NemoClaw executable or Docker daemon was
available for that acceptance here. The existing Hermes pin remains unchanged.

Do not blindly roll back to an older image after writing new disclosure/contract
JSON fields: older strict schemas may reject them. Preserve the new data, test a
compatibility migration on a restored copy, or restore a verified prechange
snapshot under an explicit recovery plan. Downgrading 0020 alone does not make
all new JSON payloads readable by old code.

## Nebius integration, deferred by user

The user will configure Nebius last. No credentials were requested or committed,
no live Nebius call was made, and the current NVIDIA deployment was not changed.

See config/nebius.env.example. Privately set NEBIUS_API_KEY and run:

```powershell
.\.venv\Scripts\python.exe -m scripts.nebius_preflight
.\.venv\Scripts\python.exe -m scripts.nebius_preflight --model "EXACT_NVIDIA_CATALOG_ID" --inference
```

Discovery makes a model-list request; --inference explicitly makes a synthetic
hosted request that may consume credits. Neither command changes the deployment.
Do not paste the API key in a command argument or public report.

After selecting a tested model, configure the existing MEMORY_PROVIDER_* and
model fields privately. Recheck structured extraction/reflection quality and
handoff categorization with that model. Keep embedding configuration separate;
changing embedding models requires a deliberate projection/reindex plan.

The default Token Factory hostname is taken from the official Nebius cookbook:
https://dev.nebius.com/cookbook/openhands-agent-canvas
Use the endpoint and model ID available in your account; there is no hardcoded
model availability assumption.

## Verification and remaining gates

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
node --check apps/api/static/portal.js
.\.venv\Scripts\python.exe -m scripts.evaluate_transfer
```

Local checkpoint: **157 passed, 14 skipped**, with the existing Starlette/httpx
deprecation warning. Ruff lint/format, JavaScript syntax and whitespace checks
passed. Migration 0019→0020 was rendered offline; it was not applied to the
personal hosted database. A synthetic local HTTP request traversed the real
API, SQL queue and worker and returned a PASS artifact with no hosted call.

The eight-case contract ablation is saved in personal-ai-evaluation.json. Its
four negative cases were rejected/withheld by the gates; unconditional reuse
would accept all four. This is a deterministic fixture result, not evidence
of improved model reasoning or a live same-model retrieval comparison.

Provider/preflight outages enter bounded WAITING/review states. A failure after
execution begins is UNCERTAIN and is not automatically replayed; prior external
effects are never represented as reversed. The user can inspect and approve a
new task after reconciliation.

The new integration tests cover real file creation, canonical state, independent
artifact checks, task idempotency, cancellation, source correction, source/file
tampering, permissions, privacy-before-network, rollback, forgetting, mocked
HTTP usage/metering and worker/service recreation. SQLite fixtures do not
establish deployed PostgreSQL concurrency or physical process crash recovery.

Browser preview infrastructure failed to initialize in this session. Static
assets and authenticated HTTP paths are checked; visual layout, touch behavior,
and browser interaction must still be tested on an actual phone/browser.

Required external acceptance: live NVIDIA model through Nebius; current Hermes
and OS sandbox deployment; Docker build and persistent hosting; live embedding
quality; sustained recovery/uptime; actual browser/phone QA; same-model semantic
retrieval-versus-skills evaluation. Do not label the submission complete until
these relevant gates have passed.
