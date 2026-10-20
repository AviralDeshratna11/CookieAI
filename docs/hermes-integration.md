# Experimental Hermes execution backend

The [approved supervisor operating notes](autonomy-operations.md) describe new
per-task tool/model budgets, independent verifiers and optional container
packaging. The compatibility pin below is preserved; the current release has
not passed replacement gates. Container builds and new live-provider acceptance
remain unverified. [Current evidence](autonomy-validation-results.json).

Prepared 20 October 2026 (Asia/Calcutta). Implementation baseline: `ba7a5f3`.

CookieAI now has an explicit `backend` selection on assistant turns. The default
is `assistant`; `hermes` is an administrator-enabled pilot. It uses the same
durable turn, context authorization, evidence revisions and ingestion services.

## What runs where

The existing API/worker owns the database, NVIDIA credential, token budgeting,
authorization and tool handlers. A fresh isolated Hermes process receives an
authorized context package and communicates over bounded JSON lines. Its OpenAI
transport sends model requests back to CookieAI; it has no model-service keys.
CookieAI continues to use its configured model and provider. No paid fallback is
enabled. The worker still owns discovery, reflection and procedure validation.

The pilot tools are bounded decimal arithmetic and read-only UTF-8 `.txt`
fixtures (8 KiB maximum) in a dedicated agent workspace. Shell, writes, network
tools, delegation, built-in memory and skill creation are unavailable. Memory
write permission alone does not authorize execution: the authenticated agent ID
must also appear in `MEMORY_HERMES_ALLOWED_AGENTS`.

The physical fixture directory is:
`<MEMORY_HERMES_WORKSPACE>/<namespace UUID>/<agent UUID>/`.
An administrator must provision approved fixtures there. Paths containing links,
traversal, Windows device names or alternative drives are rejected. Do not use a
directory writable by an adversarial local process: portable path checks do not
provide OS-level isolation against concurrent filesystem replacement.

## Version choice

[Official Hermes source](https://github.com/NousResearch/hermes-agent) is MIT
licensed. Current main was inspected at
`dfe787496a0ace8f3163c3bf86261c5bdf432253`; its package-manager runtime targets
Python 3.14. This project currently runs Python 3.11 locally.

The tested experimental compatibility pin is release `v2026.4.3` / `0.7.0`,
commit `1f6efd6eb0ba6b573c73c96d14dff1be4454823d`.
`config/hermes.lock.json` records the archive and interface hashes;
`config/hermes-requirements.lock` records the isolated dependency versions.
This older release is a compatibility choice, not a current-release security
certification. A current-release upgrade and security review remain necessary
before expanding access or deploying this executor publicly.

No upstream fork is maintained. The host uses supported custom-tool registration
and conversation entry points. Four small version-specific overrides replace
OpenAI client creation with the parent broker and disable full-request debug dumps,
incremental session logs and autonomous background review. The session-log override
is necessary because this release calls its writer after tools even when
`persist_session=False`. A retention regression caught that behavior. The pinned engine and SDK transport are tested
together; these overrides must be reviewed when changing the pin.

## Setup and use

On Windows, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.setup_hermes
```

Setup downloads the checksum-verified source and installs the locked runtime in
`.hermes-runtime/venv`. It prints the Python/source paths. It does not enable
Hermes or change CookieAI's environment. The checked-in source remains separate
from application dependencies.

Configure the process that handles turns (normally the worker), using the paths
printed by setup:

```dotenv
MEMORY_HERMES_ENABLED=true
MEMORY_HERMES_PYTHON=C:/absolute/project/.hermes-runtime/venv/Scripts/python.exe
MEMORY_HERMES_SOURCE=C:/absolute/project/.hermes-runtime/source/hermes-agent-1f6efd6eb0ba6b573c73c96d14dff1be4454823d
MEMORY_HERMES_ALLOWED_AGENTS=["an-already-provisioned-agent-UUID"]
MEMORY_HERMES_WORKSPACE=C:/absolute/project/.hermes-runtime/workspace
MEMORY_HERMES_MAX_ITERATIONS=6
MEMORY_HERMES_TIMEOUT_SECONDS=120
```

The API needs the same enablement and allowlist to accept submissions. The API
and worker must agree on configuration. This runtime is not added to the existing
Docker image: a Linux worker needs its own isolated Linux Hermes installation and
container-visible paths. Windows executable paths cannot be used inside Docker.
Container packaging and deployment acceptance remain outstanding.

Submit using the existing authenticated API:

```json
{
  "message": "Read quote.txt and calculate the total using the permitted tools",
  "idempotency_key": "unique-task-identity",
  "backend": "hermes",
  "retain": true
}
```

The CLI supports `python -m apps.cli.chat --backend hermes`. Inspect the returned
turn ID through `GET /v1/agent/turn/{turn_id}`. The response includes execution
status, usage and sanitized observation metadata. `COMPLETED` means the host
produced a final response; `task_success` remains unknown until evaluated or
explicitly confirmed. The turn's completion status is separate from execution
success.

Cancel through `POST /v1/agent/turn/{turn_id}/cancel`. Cancellation fences the SQL
job and future broker operations; the host is terminated when the broker regains
control. An in-flight provider request may finish before that check. No claim is
made that cancellation reverses prior external effects.

## Durability, evidence and retention

The executor claims `EXECUTING` durably before launch. Tool start/completion
metadata is journaled on the existing turn before returning each observation to
Hermes. IDs are stable within a run. Arguments and raw outputs are excluded from
the journal. Finished observations enter an evidence-linked episode with unknown
task outcome; they do not automatically establish a successful learned procedure.

A retry encountering a previously executing turn preserves recorded attempts and
reports an unknown execution outcome. It does not relaunch the task. Lost or
unfinished attempts remain uncertain. This pilot does not promise exactly-once
external execution or crash-safe writes for arbitrary tools.

Before each model/tool operation, and before observation persistence, the broker
rechecks authorization, source revisions, turn state and the worker lease where
present. Erasure/cancellation prevents late callbacks from restoring data.
Recorded episodes depend on authorized context and newly ingested user memories,
so existing descendant invalidation applies.

Hermes sessions, trajectories, built-in memory, automatic compression, project
context loading and background reviews are disabled. Each host has a fresh
temporary profile and sanitized environment; normal completion/error cleanup
removes it. Tests check that the synthetic prompt is absent from profile files
during execution and that the directory is removed afterward. Abrupt OS/parent
death and historical provider retention are not covered. Consequently,
`backend:hermes` with `retain:false` is explicitly rejected. Do not claim complete
crash-retention or provider-erasure guarantees.

The parent checks serialized messages, tools, reserved output and a configurable
chat-template allowance before every model request. Provider accounting can
differ; the allowance is not an exact measurement of a private chat template.

## Validation and observed value

Final local regression: **122 passed, 11 skipped** in 89.65 seconds on Python
3.11.0, including both real-engine scripted tests. Lint, formatting and whitespace
checks passed. The pinned setup command was also exercised using its
`--archive .hermes-review/compatible.zip` cached-archive option. See
[machine-readable validation](hermes-validation-results.json) for scope, skipped
checks and implementation hashes. No live PostgreSQL/Redis or Docker outage
acceptance was performed in this follow-up because Docker was unavailable.

`tests/integration/test_hermes_execution.py` covers replay protection, durable
attempt preservation, cancellation, erasure, legacy request hashes and observation
ingestion. Optional real-engine tests use deterministic scripted model responses:
a failed division followed by corrected arithmetic, and four distinct executions
covering explicit outcome feedback, procedure compilation, later-session reuse
and reduced confidence after counterevidence. Task-context labels supplied by the
caller are bounded and preserved for structural matching. These are actual
Hermes orchestration tests with a test-double model, not evidence of model
reasoning or statistically independent real-world experience.

Run the real-engine fixture with the isolated runtime paths:

```powershell
$env:COOKIEAI_HERMES_PYTHON = "C:/absolute/path/to/python.exe"
$env:COOKIEAI_HERMES_SOURCE = "C:/absolute/path/to/pinned/source"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_hermes_execution.py -q
```

For a bounded live NVIDIA smoke comparison:

```powershell
.\.venv\Scripts\python.exe -m scripts.acceptance_hermes --python C:/absolute/path/to/python.exe --source C:/absolute/path/to/pinned/source
```

[Recorded live results](hermes-live-results.json) use only a synthetic quote file.
The assistant could not read the fixture. Hermes read it, called the calculator
and returned the correct total `94.25` in approximately 19.3 seconds, using three
model calls, 2,171 input tokens and 71 output tokens. The assistant response took
approximately 2.4 seconds. These are one-run smoke measurements, not p95 latency,
representative task success, or proof that Hermes outperforms a smaller custom
tool loop. Hermes remains opt-in.

## Rollback and outstanding acceptance

Set `MEMORY_HERMES_ENABLED=false` on API and worker and restart them. Keep the
default `assistant` backend. Existing turns and their evidence remain readable.
Do not replay uncertain executions; review their state separately. No Hermes
database migration or hosted cutover is required by this pilot.

Remaining Hermes work includes a current-runtime upgrade, container packaging,
representative same-model comparisons, live-model longitudinal learning/reuse,
real PostgreSQL/Redis execution fencing, multi-worker capacity, crash-retention
drills, externally verified task outcomes and any broader tool permissions.
