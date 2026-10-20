# Approved continuous execution

Local implementation, 20 October 2026. This is a bounded task supervisor, not
certification of the complete CookieAI specification. See the
[requirement/evidence checkpoint](autonomy-execution-ledger.md).

## Ownership and startup

FastAPI accepts an authenticated task approval. PostgreSQL stores the immutable
definition, original approver, revisions, task/run state and observations.
The existing SQL job queue and worker schedule and execute the task. Redis
continues to carry operational notifications. Canonical memory, ACLs, provenance,
source revisions, learning and forgetting remain CookieAI-owned. Hermes is an
optional brokered executor; it receives neither database authority nor provider
credentials. The default assistant remains available.

Migration **0019** adds five namespace-isolated tables. Prepare/review migration
0018 first if the deployed schema is older. Offline rendering was checked; the
active hosted database was not migrated. The migration enables/forces RLS and
revokes public, anon and authenticated access on the operational tables. Apply
with the deployment's migration identity, not its application identity. Review
application-role grants and backup/restore on a disposable database first.

Set these identically on API and worker after migration:

```dotenv
MEMORY_AUTONOMY_ENABLED=true
MEMORY_AUTONOMY_ALLOWED_AGENTS=["<approved authenticated agent UUID>"]
MEMORY_AUTONOMY_INTERVAL_SECONDS=30
MEMORY_AUTONOMY_DAILY_TOOL_CALLS=100
MEMORY_AUTONOMY_DAILY_MODEL_CALLS=50
```

Both enabled status and an exact authenticated-agent allowlist are required.
Enabling the supervisor does not enable Hermes. That requires its separate
enabled setting, agent allowlist and isolated runtime paths described in
[Hermes integration](hermes-integration.md). NVIDIA/Nemotron provider settings
are unchanged. No paid fallback was introduced.

The optional `docker-compose.hermes.yml` overlay selects
`docker/Dockerfile.hermes` for API and worker, installs the checksum-pinned Hermes
source in its own virtual environment, and mounts a shared scoped workspace.
The default stack keeps its existing image. For a **disposable local stack**:

```powershell
docker compose -f docker-compose.yml -f docker-compose.hermes.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.hermes.yml build api worker
docker compose -f docker-compose.yml -f docker-compose.hermes.yml up -d
```

The `up` command starts the existing migration service: inspect its target first.
These commands were not used to apply a hosted migration. Compose configuration
validation passed; build/start remain unverified because Docker Desktop's engine
was unavailable. The Windows host runtime was tested separately. The PC must
remain powered and available; independent hosting still requires a target.

The official [latest release](https://github.com/NousResearch/hermes-agent/releases/latest)
resolved to v0.22.2 during this pass. The previous audited 0.7.0 compatibility pin
is preserved. Current-release compatibility, override/retention audit and Linux
container acceptance have not passed, so no upgrade or security attestation is
claimed. Dependency versions are pinned; cross-platform wheels/builds still need
validation. Startup never downloads Hermes.

## API and task approval

Existing authentication/context requirements apply. Endpoints:

| Method/path | Behavior |
|---|---|
| `POST /v1/tasks` | Approve immutable definition; 202; idempotent per namespace/agent/key |
| `GET /v1/tasks?after=<UUID>&limit=20` | Owner-scoped cursor page, maximum 100 |
| `GET /v1/tasks/status` | Authorized bounded progress window, verdicts and UTC daily usage |
| `GET /v1/tasks/<UUID>` | Definition/state and latest ten sanitized run journals |
| `POST /v1/tasks/<UUID>/control` | Pause/resume/cancel with expected revision |

Create an existing authorized goal first, then submit, for example:

```json
{
  "goal_id": "<existing authorized goal UUID>",
  "objective": "Independently check the approved arithmetic result",
  "idempotency_key": "approved-calculation-v1",
  "backend": "deterministic",
  "complete_goal_on_success": true,
  "allowed_tools": ["cookieai_calculate"],
  "steps": [{"tool": "cookieai_calculate", "arguments": {"expression": "2+2"}}],
  "verifier": {"kind": "DECIMAL_RESULT", "step_index": 0, "expected": "4"},
  "max_runs": 1,
  "max_tool_calls": 1,
  "max_model_calls": 0,
  "timeout_seconds": 30,
  "evidence_origin": "SYNTHETIC"
}
```

This example is synthetic and cannot activate real-world procedures. Use `REAL`
only for actual observations, not demonstrations or copied fixtures. Explicit
`REHEARSAL` tasks require `evidence_origin=REHEARSAL`. Origin labels are supplied
by the authorized producer; their authenticity is not inferred from content.

For Hermes, select `backend=hermes`, allow a positive bounded model-call budget
and describe the approved objective. CookieAI still fixes the tool subset,
criteria, workspace, deadlines and budgets. A model narrative never certifies
completion. Hermes does not inherit unlisted tools from a retrieved procedure.

Use `start_at` for delayed work, `repeat_seconds` and `max_runs` for bounded
repetition, `depends_on` for same-owner/same-goal task dependencies, and
`parent_task_id` for an explicit same-goal hierarchy. `max_evaluations` bounds
waiting checks. Task expansion by a model is not implemented. For events, approve
`trigger=EVENT` and explicit `event_topics`; only authorized canonical outbox
events created after approval can wake the subscription. Receipts deduplicate
events; generated/derived sources cannot self-trigger. Events during a run
coalesce. At most 500 active event subscriptions exist per namespace.

Pin a reusable procedure with `required_procedure_id` and `procedure_revision`.
Known fingerprint conditions must remain unchanged; structural similarity is an
additional gate, not permission to ignore a changed environment. Artifact
`preconditions` independently recheck provisioned workspace data before actions.
An unmet precondition records its actual verdict, executes no action, consumes
one bounded run evaluation, and stops or retries within the original approval.
Generic natural-language procedure preconditions are not executable tests.

## Tools, verifiers and limits

| Tool | Inputs and scope | Result / verification | Recovery |
|---|---|---|---|
| `cookieai_calculate` | Exact `expression` string, 1-200 characters; bounded AST/Decimal arithmetic | Decimal receipt; `DECIMAL_RESULT` checks an approved expected value | Read-only; unknown run is still not automatically replayed |
| `cookieai_read_text` | Exact relative `path`, max 200 characters, physical per-agent workspace, regular UTF-8 `.txt`, max 8 KiB | Content returned transiently; digest/length journaled; independent artifact reread | Read-only; links/devices/traversal rejected |

Workspace: `<MEMORY_HERMES_WORKSPACE>/<namespace UUID>/<agent UUID>/`.
An administrator provisions inputs. The directory must not be writable by an
adversarial process; path validation is not OS-level isolation against races.
No shell, network-service requests or file writes are exposed as task tools.

Verifiers are `DECIMAL_RESULT`, `TEXT_EXISTS`, `TEXT_SHA256` and `JSON_FIELDS`.
JSON fields require exact expected value types. File checks use the same scoped
8 KiB read operation. At most five artifact preconditions and one final check run
per attempt. They have authorization/deadline guards before and after checks;
these fixed verifier reads are separate from the execution-tool counter. A zero
exit code, tool success or summary is not a substitute for a completion criterion.
Test-command and service-health verifiers are not yet implemented.

No arbitrary adapter registration endpoint exists. To add a tool, implement its
typed schema, parent-owned capability/scope checks, bounded handler, verifier,
reconciliation and tests; update the broker and runner subset. Writes require a
separate explicit policy and side-effect reconciliation before exposure.

Daily budgets apply to supervisor execution per namespace/agent and UTC date.
Each attempted tool/model operation is durably charged before dispatch with a
stable charge identity. Content-free charges survive task deletion. These caps
do not cover all pre-existing reflection/extraction provider calls. Request
budgets are separate from monetary billing; no monetary estimates are claimed.

## Recovery, retention and learning

States: QUEUED, RUNNING, WAITING, PAUSED, COMPLETED, FAILED, CANCELLED, EXHAUSTED,
UNCERTAIN. Leased runs journal intent before action and result afterward. A lost
lease yields UNCERTAIN and no automatic replay. Inspect observed state, then
create a new explicit approval when appropriate; terminal tasks cannot resume.
Pause/cancel fences active callbacks. Revoked approval pauses scheduling and
cannot monopolize the next scheduling batch. Corrected approval evidence waits
for review without polling stale content. A verified task may close its goal
only when explicitly approved to do so; other goal tasks then stop at evaluation.

Cancellation does not reverse external effects. Service shutdown and queue lease
renewal use the existing worker machinery. Actual OS death, concurrent production
workers and PostgreSQL/Redis outages still require deployment drills.

Each completed attempt records actual typed operations, failure classes,
verification and source revisions. Verified outcomes generate canonical evidence
and episodes; only REAL episodes enter real-outcome projection/procedure gates.
Distinct observation sessions are an attribution proxy, not proof of independent
samples. Raw file content and model summaries are not retained in task outcomes.
Task definitions and approved short parameters remain private evidence.

Context includes relevant failures and exceptions. Contrastive discovery compares
bounded real-labeled outcome cohorts, deduplicates session/event identities and
stores candidate associations with exposure counts, limitations and alternative
explanations. Candidates are excluded from ordinary active-memory retrieval.
Changed evidence revises/invalidates them; no causal claim or automatic procedure
activation follows. At most 200 recent episodes, 50 observations per cohort,
100 candidate comparisons and eight persisted changes per pass are used.

Run utility metadata identifies supplied revisions, retrieval latency, observed
action count and the verified outcome. It explicitly leaves causal influence
unmeasured and does not change truth confidence. Held-out memory-benefit
evaluation and an automatic rehearsal curriculum remain engineering work.

Source/task/session forgetting scrubs dependent execution contexts and journals,
fences leases/jobs, and follows canonical provenance. Content-free quota totals
and charge IDs intentionally remain. This is not a claim about provider logs,
historical backups or deleting arbitrary administrator-provisioned files.
Hermes `retain:false` remains rejected under the existing policy.

Use the existing backup/restore/alert runbooks for deployment preparation; new
tables must be included in restore drills. Reverting application code alone
does not roll back schema/data. Migration downgrade 0019 removes all new task,
run, subscription and quota tables, so export/reconcile approved work first.
No schema downgrade or backup deletion was performed in this pass.
