# CookieAI: complete teammate setup from scratch

Prepared 20 October 2026 (Asia/Calcutta), against commit `70038fe`.
Primary commands use **Windows PowerShell**. Run project commands from the
repository root. macOS/Linux equivalents are included below.

This guide creates a teammate's **own development environment**. A clone does
not include the owner's private configuration, accounts, database, bearer token
or memory history. Read [implemented and remaining work](implemented-and-remaining.md)
for the system's current limits; installation does not establish production readiness.

## 1. Choose a setup

| Option | Purpose | Extra accounts |
|---|---|---|
| Recommended: local PostgreSQL/Redis/API/worker + NVIDIA models | Personal model-backed development | Authorized NVIDIA API access |
| Local infrastructure + hash-test embeddings | Provider-free plumbing and deterministic tests | None; chat/inferred extraction still need a generation provider |
| Optional Supabase database + NVIDIA | Separately provisioned hosted development database | Supabase project/database access and NVIDIA access |
| Optional Hermes/autonomy | Approved bounded execution after basic setup | Isolated runtime and explicit agent enablement |

The stack is Python/FastAPI, SQLAlchemy/Alembic, PostgreSQL/pgvector and Redis.
No Node/npm installation is required. Docker supplies PostgreSQL, pgvector and
Redis; do not separately install those on Windows for the recommended route.
**No GPU, Ollama or model-weight download is needed for hosted NVIDIA mode.**

Planning allowance, not measured minimums: supported 64-bit OS, hardware
virtualization, preferably 16 GB RAM and 15-20 GB free disk for dependencies,
Docker images and caches. Data/backups need additional space. Check the current
Docker requirements for the machine.

## 2. Install prerequisites

### Git and editor

Install [Git for Windows](https://git-scm.com/install/windows), reopen PowerShell,
and verify `git --version`. An editor such as VS Code is useful but optional.
Authenticate to GitHub with your own authorized account if the repository
requires it. Never embed another teammate's token in a clone URL.

### Python

Use **Python 3.12** to match Docker. Recorded host tests also use 3.11. The newest
Python release is not automatically compatible with this dependency lock.

Install the official [Python install manager](https://www.python.org/downloads/windows/),
then:

```powershell
py install 3.12
py -3.12 --version
```

`py install` requires the modern install manager. If you have the legacy launcher,
install 3.12 through the official installer/manager first and use `py -3.12`.
Use standard 64-bit Python, not the embeddable distribution. See the
[official Windows Python instructions](https://docs.python.org/3/using/windows.html).

### WSL 2 and Docker Desktop

Follow [Microsoft's WSL setup](https://learn.microsoft.com/en-us/windows/wsl/install)
and [Docker Desktop's Windows installation](https://docs.docker.com/desktop/setup/install/windows-install/).
If WSL is absent, run in **administrator PowerShell**:

```powershell
wsl --install
```

Restart if requested. Then:

```powershell
wsl --update
wsl --status
wsl --list --verbose
```

Install/start Docker Desktop, choose its WSL 2 backend and **Linux containers**.
Enable hardware virtualization in BIOS/UEFI if Docker requires it. Distribution
integration is needed if running inside WSL; these commands use Windows PowerShell.

```powershell
git --version
docker version
docker compose version
docker info
```

`docker version` must show a working **Server**, not only Client. A missing
Docker Desktop Linux-engine pipe means the engine is unavailable. Use current
Compose v2 (`docker compose`); the optional hosted overlay uses `!reset`, which
older versions do not understand. Check Docker Desktop licensing for your organization.

### Network and model account

Allow approved outbound access to GitHub, Python package indexes, Docker
registries and NVIDIA. Optional tokenizer fetching uses Hugging Face; Hermes
downloads GitHub source and Python packages. Configure corporate proxy/CA
requirements through approved mechanisms; do not disable TLS checks.

Obtain API access from the official model pages using your own authorized account:

- [NVIDIA Nemotron Ultra](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b)
- [NVIDIA Nemotron Embed](https://build.nvidia.com/nvidia/nemotron-3-embed-1b)

Confirm current model access, terms and quotas. No paid fallback is enabled by
this guide; hosted inference is not guaranteed to be unlimited or permanently free.

## 3. Clone and install project dependencies

Prefer a short local path outside OneDrive/synchronized folders:

```powershell
New-Item -ItemType Directory -Force C:\dev | Out-Null
Set-Location C:\dev
git clone https://github.com/AviralDeshratna11/CookieAI.git
Set-Location CookieAI
git status
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import fastapi, sqlalchemy, psycopg, pgvector, redis; print('Imports OK')"
```

The lock includes application and test/lint dependencies. Editable installation
registers the local source; build dependencies are installed by pip as specified
in `pyproject.toml`. Keep the lock-first sequence rather than resolving new
application versions with an unconstrained install.

Use `.venv\Scripts\python.exe` for every project Python command. Activation is
optional; explicit paths avoid PowerShell activation policy errors and selecting
the wrong interpreter. No global Python package install is needed.

If pip attempts native compilation, first check supported Python/architecture,
wheel availability and package-index/proxy settings. Install approved build
tools only if actually required; do not silently replace the lock versions.

## 4. Required files and where they come from

| File/directory | Source | Purpose |
|---|---|---|
| `pyproject.toml`, `requirements.lock` | Git | Python project and dependency versions |
| `docker-compose.yml`, `docker/` | Git | Local database, Redis, migration, API and worker |
| `database/migrations/`, `alembic.ini` | Git | Versioned schema; snapshot head **0019** |
| `config/memory.yaml`, `prompts/` | Git | Policy defaults and prompts |
| `.env.example` | Git | Template with historical/local-provider defaults |
| `.env` | Create locally | Personal database/model/runtime settings; ignored |
| `config/credentials.json` | Bootstrap | Token digest plus application identity; ignored |
| `config/worker-context.json` | Worker provisioning | Separate read/write worker context; ignored |
| `config/tokenizer-manifest.json` | Git | Public pinned tokenizer metadata/hash |
| `config/nemotron-tokenizer.json` | Optional fetch script | Public tokenizer artifact; ignored |
| `.env.supabase` | Optional, create locally | Hosted Compose URLs; ignored |
| `.env.cloud` | Optional existing-team convention | Separate model overrides; not required by this single-`.env` guide |
| `.hermes-runtime/` | Optional Hermes installer | Isolated runtime/source/workspace; ignored |
| `backups/` | Backup scripts | Private dumps; ignored |

Do not copy another machine's `.venv`, absolute paths or private files into Git.
GitHub does not supply the private files. Joining shared infrastructure requires
authorized account/credential provisioning through an approved channel.

## 5. Create configuration

Run once, then edit the copy:

```powershell
Copy-Item .env.example .env
notepad .env
```

For a **new local database + NVIDIA** setup, replace the corresponding entries
with the following. Keep only one active value for each key. Replace placeholders.

```dotenv
# Local development passwords only; choose stronger credentials for other deployments.
POSTGRES_PASSWORD=memory-local-only
MEMORY_APP_PASSWORD=memory-app-local-only
MEMORY_POSTGRES_PORT=55432
MEMORY_API_PORT=8000
MEMORY_DATABASE_URL=postgresql+psycopg://memory_app:memory-app-local-only@127.0.0.1:55432/memory
MEMORY_MIGRATION_DATABASE_URL=postgresql+psycopg://memory:memory-local-only@127.0.0.1:55432/memory
MEMORY_CREDENTIALS_FILE=config/credentials.json
MEMORY_REDIS_URL=redis://127.0.0.1:6379/0

MEMORY_PROVIDER_BASE_URL=https://integrate.api.nvidia.com/v1
MEMORY_PROVIDER_API_KEY=REPLACE_WITH_YOUR_NVIDIA_KEY
MEMORY_EXTRACTION_MODEL=nvidia/nemotron-3-ultra-550b-a55b
MEMORY_EXTRACTION_RESPONSE_FORMAT=prompt_json
MEMORY_PROVIDER_ENABLE_THINKING=false
MEMORY_REASONING_EFFORT=none
MEMORY_REQUEST_TIMEOUT_SECONDS=180

MEMORY_EMBEDDING_BACKEND=compatible
MEMORY_EMBEDDING_PROVIDER_BASE_URL=https://integrate.api.nvidia.com/v1
MEMORY_EMBEDDING_PROVIDER_API_KEY=REPLACE_WITH_YOUR_NVIDIA_KEY
MEMORY_EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b
MEMORY_EMBEDDING_VERSION=nemotron3-embed-1b-2048-v1
MEMORY_EMBEDDING_DIMENSIONS=2048
MEMORY_EMBEDDING_INPUT_TYPE_MODE=nvidia
MEMORY_EMBEDDING_DOCUMENT_PREFIX=
MEMORY_EMBEDDING_QUERY_PREFIX=

MEMORY_REFLECTION_BACKEND=compatible
MEMORY_REFLECTION_MODEL=nvidia/nemotron-3-ultra-550b-a55b
MEMORY_CRITIC_MODEL=nvidia/nemotron-3-ultra-550b-a55b
MEMORY_GENERAL_DISCOVERY_ENABLED=true
MEMORY_REFLECTION_MAX_MODEL_CANDIDATES=1
MEMORY_REFLECTION_INTERVAL_SECONDS=600
MEMORY_SERENDIPITY_INTERVAL_SECONDS=3600
MEMORY_DAILY_INTERVAL_SECONDS=86400
MEMORY_DREAMER_INTERVAL_SECONDS=604800

MEMORY_HERMES_ENABLED=false
MEMORY_HERMES_ALLOWED_AGENTS=[]
MEMORY_AUTONOMY_ENABLED=false
MEMORY_AUTONOMY_ALLOWED_AGENTS=[]
MEMORY_ASSISTANT_PROMPT_TOKENS=32768
MEMORY_ASSISTANT_OUTPUT_TOKENS=2000
MEMORY_ASSISTANT_TEMPLATE_RESERVE_TOKENS=512
MEMORY_CONTEXT_TOKENIZER_FILE=
```

Background model-assisted reflection consumes provider quota. To initially use
only rule-based reflection, set `MEMORY_REFLECTION_BACKEND=rules` and
`MEMORY_GENERAL_DISCOVERY_ENABLED=false`; assistant/extraction still use their
configured generation provider.

The embedding version above is a chosen label for a fresh empty database. For
existing data use the team's **exact** model/version/dimensions/prefixes. Changing
the model requires deliberate memory/entity reindexing; equal dimensions do not
mean compatible vectors.

Host Settings load `.env`; existing shell `MEMORY_*` variables take precedence.
Compose uses `.env` interpolation and only forwards variables declared in its
service configuration. Ordinary host Python does not automatically load
`.env.cloud`/`.env.supabase`; the hosted section distinguishes the required keys.

### Provider-free infrastructure mode

Before creating data, these replacements enable deterministic test embeddings:

```dotenv
MEMORY_EMBEDDING_BACKEND=hash-test
MEMORY_EMBEDDING_MODEL=hash-test
MEMORY_EMBEDDING_VERSION=1
MEMORY_EMBEDDING_DIMENSIONS=64
MEMORY_EMBEDDING_INPUT_TYPE_MODE=prefix
MEMORY_EMBEDDING_DOCUMENT_PREFIX=
MEMORY_EMBEDDING_QUERY_PREFIX=
MEMORY_REFLECTION_BACKEND=rules
MEMORY_GENERAL_DISCOVERY_ENABLED=false
```

Use raw/direct storage and deterministic tests. Chat, inferred extraction and
Hermes still require a generation provider. Hash-test is not semantic-quality
embedding. Switching an existing store to real embeddings requires an intentional
reindex or a separate disposable database, not just changing the environment.

### Optional public tokenizer

```powershell
.\.venv\Scripts\python.exe -m scripts.fetch_tokenizer
```

Then set `MEMORY_CONTEXT_TOKENIZER_FILE=config/nemotron-tokenizer.json` in `.env`.
The script verifies the pinned public artifact/hash and does not download model
weights. Fetch **before Docker build**, because the image copies `config/`.
Relative paths resolve under `/app` in Docker. A Windows absolute path cannot
be used inside Linux containers. Without the configured file the code uses its
explicitly labeled conservative fallback.

## 6. Start local database/Redis and initialize identities

This section targets your **own local database**. Verify both database URLs
before running administrative commands; do not point them at the owner's system.

```powershell
docker compose up -d postgres redis
docker compose ps
docker compose exec -T postgres pg_isready -U memory -d memory
docker compose exec -T redis redis-cli ping
```

Expect PostgreSQL ready/healthy and Redis `PONG`. If not ready, wait and inspect
`docker compose logs --tail 100 postgres redis` before continuing.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m apps.cli.provision_role
.\.venv\Scripts\python.exe -m apps.cli.bootstrap
.\.venv\Scripts\python.exe -m apps.cli.provision_worker
```

Expected migration head: **0019**. A fresh Docker volume creates `memory_app`
through its initialization script; `provision_role` ensures application grants
and verifies no superuser/RLS bypass. Runtime uses `memory_app`; migrations and
bootstrap use the administrative connection. Do not fix permission errors by
running the API as superuser or disabling RLS.

**Save the bearer token printed by bootstrap immediately in your password
manager.** It is printed once. `config/credentials.json` stores the digest and
identity metadata, not the recoverable raw token. Bootstrap refuses to overwrite
an existing credential file. The worker gets a different read/write agent with
no delete grant.

```powershell
Test-Path config/credentials.json
Test-Path config/worker-context.json
```

Both must be `True`. For the bundled chat CLI, add to the ignored `.env`:

```dotenv
MEMORY_LOCAL_TEST_TOKEN=REPLACE_WITH_BEARER_TOKEN_FROM_BOOTSTRAP
```

This is **CookieAI's token**, not the NVIDIA key or a Supabase key. Never post it
in shared logs. If lost, coordinate credential rotation preserving the identity;
deleting the file and rerunning bootstrap creates a new user/namespace and does
not recover access to the old one. Do not rerun bootstrap as a daily startup step.

## 7. Start API and worker

After both private files exist:

```powershell
docker compose config --quiet
docker compose up --build -d api worker
docker compose ps -a
docker compose logs --tail 100 migrate api worker
Invoke-RestMethod http://127.0.0.1:8000/health/live
```

The one-shot `migrate` service should exit with code 0. API/worker remain running;
worker health may need its startup grace period. Redis is required for events
and the default container rate limiter.

| Address | Purpose |
|---|---|
| `http://127.0.0.1:8000` | API base |
| `http://127.0.0.1:8000/docs` | Swagger requests |
| `http://127.0.0.1:8000/openapi.json` | Current live contract |
| `http://127.0.0.1:8000/health/live` | Process liveness only |

Liveness is not proof of database/provider access, worker progress or retrieval
quality. Complete the authenticated smoke checks below.

### Alternative: host Python for debugging

Keep Docker PostgreSQL/Redis running, but stop its API/worker to avoid duplicate
workers or an API port conflict:

```powershell
docker compose stop api worker
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

In a second PowerShell terminal at the same repository root:

```powershell
.\.venv\Scripts\python.exe -m apps.worker.main
```

Ctrl+C shuts these processes down. Both load `.env`. NVIDIA API URLs work from
host and Docker. For an optional local model server, host Python uses localhost;
Docker Desktop generally uses `host.docker.internal` to reach the PC. Container
`localhost` refers to that container. Linux Engine needs appropriate host mapping.
The project does not automatically install any local model.

## 8. Verify authentication, memory and chat

Read your local token without displaying it and prepare headers:

```powershell
$cookieToken = .\.venv\Scripts\python.exe -c "from dotenv import dotenv_values; print(dotenv_values('.env')['MEMORY_LOCAL_TEST_TOKEN'])"
$cookieHeaders = @{
    Authorization = "Bearer $cookieToken"
    'X-Session-ID' = [guid]::NewGuid().ToString()
    'X-Purpose' = 'Teammate onboarding smoke check'
}
```

Protected requests need all three headers. The bearer binds user/agent/namespace
server-side; arbitrary namespace headers cannot impersonate another user.
Swagger's Authorize field takes the raw token; provide session/purpose fields on
each operation too.

### Store and retrieve one disposable fact

```powershell
$cookieBody = @{
    text = 'Onboarding fixture: Project Juniper uses PostgreSQL.'
    type = 'SEMANTIC'
    epistemic_type = 'USER_STATED'
    source_type = 'MESSAGE'
} | ConvertTo-Json
$cookieMemory = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/memory -Headers $cookieHeaders -ContentType 'application/json' -Body $cookieBody
$cookieSearch = @{ query = 'Project Juniper PostgreSQL'; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/memory/search -Headers $cookieHeaders -ContentType 'application/json' -Body $cookieSearch
Invoke-RestMethod -Uri http://127.0.0.1:8000/v1/operations/status -Headers $cookieHeaders
```

Expect a memory ID and matching result. NVIDIA mode invokes actual embedding
requests here. Hash-test mode checks deterministic lexical plumbing. To remove
only this deliberately created fixture afterward:

```powershell
Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/v1/memory/$($cookieMemory.memory_id)" -Headers $cookieHeaders
```

### Durable assistant across sessions

With a working generation provider and worker:

```powershell
.\.venv\Scripts\python.exe -m apps.cli.chat --message "Remember that my onboarding project is Juniper and it uses PostgreSQL."
.\.venv\Scripts\python.exe -m apps.cli.chat --message "What database does my onboarding project Juniper use?"
```

These use separate sessions by default. The CLI prints a durable turn ID. Inspect
`GET /v1/agent/turn/<turn_id>`, `/v1/jobs` and worker logs if queued. Interactive
mode is `.venv\Scripts\python.exe -m apps.cli.chat`; `--session <UUID>` continues
one conversation. Neither a successful smoke check nor the model's narrative
establishes broad memory accuracy.

## 9. Tests and acceptance

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check apps database memory models workers scripts tests
```

Recorded baseline: **139 passed, 14 skipped**. Default tests use deterministic
fixtures; unconfigured external gates are explicitly skipped, not passed.

For actual store tests, use **your disposable local PostgreSQL/Redis**, never a
shared hosted database. The test role needs temporary schema/role privileges.
Redis database 15 separates tests from application DB 0:

```powershell
$env:MEMORY_TEST_DATABASE_URL='postgresql+psycopg://memory:memory-local-only@127.0.0.1:55432/memory?connect_timeout=5'
$env:MEMORY_TEST_REDIS_URL='redis://127.0.0.1:6379/15'
.\.venv\Scripts\python.exe -m pytest -q -rs
Remove-Item Env:MEMORY_TEST_DATABASE_URL
Remove-Item Env:MEMORY_TEST_REDIS_URL
```

Adjust the test URL if you changed local passwords/ports. Live-provider tests
remain separately opt-in; inspect their code/quotas first. Historical reports in
`docs/` describe their recorded environments, not automatic acceptance of a new PC.

## 10. Optional fresh Supabase database

Skip this if local PostgreSQL is enough. Create your own authorized project or
get explicit team development-database access. Do not reuse the owner's private
project merely because a URL is mentioned in historical docs.

In the dashboard's Connect panel copy the exact database details. On an IPv4-only
PC, use **Session pooler**. Check the official
[Postgres connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).
Use TLS (`sslmode=require` at minimum; apply your deployment's certificate
verification policy), percent-encode URI passwords and use SQLAlchemy's
`postgresql+psycopg://` scheme. Do not guess pooler regions or use the web project
URL as the Postgres host.

The following administrative steps require a **fresh dedicated project** or a
database owner's approved backup/migration plan. For host CLI commands, set in `.env`:

```dotenv
MEMORY_MIGRATION_DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:ENCODED_DATABASE_PASSWORD@SESSION_POOLER_HOST:5432/postgres?sslmode=require
MEMORY_APP_PASSWORD=REPLACE_WITH_NEW_STRONG_APPLICATION_ROLE_PASSWORD
MEMORY_DATABASE_URL=postgresql+psycopg://memory_app.PROJECT_REF:ENCODED_APPLICATION_ROLE_PASSWORD@SESSION_POOLER_HOST:5432/postgres?sslmode=require
```

Custom-role session-pooler usernames commonly use `role.PROJECT_REF`; confirm
the exact project format. Direct connections use their direct host/user details,
not this pooler suffix. Supabase anon/publishable/service-role API keys are not
database passwords or CookieAI bearer tokens. This backend uses Postgres, not
Supabase Auth as application login.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m apps.cli.provision_role
```

`provision_role` does not rotate an existing `memory_app` password. Coordinate
existing roles with the owner. Have the administrator verify pgvector, forced
namespace RLS and least-privilege application grants, and revoke public/anon/
authenticated Data API access to private CookieAI tables. Public Data API access
is not needed. Do not replace CookieAI's namespace policies with unrelated
`auth.uid()` policies or grant runtime superuser/BYPASSRLS.

For a **fresh dedicated CookieAI project only**, the administrator can run this
in the Supabase SQL editor after migrations/provisioning to remove Data API
table access and inspect the database controls:

```sql
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'memory_app';
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname;
```

Do not apply a schema-wide revoke to a shared project serving unrelated apps.
Expected: vector installed and both runtime-role bypass flags false. Inspect
RLS flags for application tables and their namespace policies; migration metadata
such as `alembic_version` is not an application memory table. Recheck private
grants when adding future migrations; a one-time revoke is not a permanent
default-privilege policy. Then complete authenticated write/search from section 8
against the hosted configuration, not just an administrative connectivity test.

Create ignored `.env.supabase` for Compose's distinct variable names:

```dotenv
MEMORY_HOSTED_MIGRATION_DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:ENCODED_DATABASE_PASSWORD@SESSION_POOLER_HOST:5432/postgres?sslmode=require
MEMORY_HOSTED_DATABASE_URL=postgresql+psycopg://memory_app.PROJECT_REF:ENCODED_APPLICATION_ROLE_PASSWORD@SESSION_POOLER_HOST:5432/postgres?sslmode=require
```

Bootstrap and provision the worker against this new hosted database using section
6's identity commands after schema/grants are ready. If already bootstrapped
locally, keep separate environment-specific identity files/configuration through
an agreed maintainer workflow; local files alone do not create remote users.
Do not delete or overwrite working identity files blindly.

```powershell
docker compose --env-file .env --env-file .env.supabase -f docker-compose.yml -f docker-compose.hosted.yml config --quiet
docker compose --env-file .env --env-file .env.supabase -f docker-compose.yml -f docker-compose.hosted.yml up --build -d redis api worker
```

The hosted overlay starts its **hosted migration service** as a dependency:
starting it may apply migrations. Review the target first. Local `postgres`
isn't needed for hosted application traffic; API/worker/Redis still run on the
PC. Repeat the same `--env-file` and `-f` options for later lifecycle commands.

Do not run historical `scripts.migrate_hosted`, embedding cutover or runtime
upgrade scripts as setup shortcuts; they contain data-changing workflows for
existing installations. This guide performs no data copy from another teammate.

## 11. Optional Hermes

Finish basic memory/chat first. Hermes remains a brokered optional executor;
CookieAI owns memory, permissions, budgets and verification. Use the checked-in
compatibility pin, not an unreviewed latest upstream installation.

### Host API/worker

```powershell
.\.venv\Scripts\python.exe -m scripts.setup_hermes
$cookieAgent = (Get-Content config/credentials.json -Raw | ConvertFrom-Json)[0].agent_id
$cookieAgent
```

Setup downloads checksum-verified source and installs locked dependencies into
`.hermes-runtime/venv`; it prints paths and does not enable the feature. Set in `.env`:

```dotenv
MEMORY_HERMES_ENABLED=true
MEMORY_HERMES_ALLOWED_AGENTS=["REPLACE_WITH_APPLICATION_AGENT_UUID"]
MEMORY_HERMES_PYTHON=C:/dev/CookieAI/.hermes-runtime/venv/Scripts/python.exe
MEMORY_HERMES_SOURCE=C:/dev/CookieAI/.hermes-runtime/source/hermes-agent-1f6efd6eb0ba6b573c73c96d14dff1be4454823d
MEMORY_HERMES_WORKSPACE=C:/dev/CookieAI/.hermes-runtime/workspace
MEMORY_HERMES_MAX_ITERATIONS=6
MEMORY_HERMES_TIMEOUT_SECONDS=120
```

Use the actual printed paths. Restart both host API and worker. The allowlist
normally names the authenticated application agent submitting work, not the
separate service worker's UUID.

```powershell
.\.venv\Scripts\python.exe -m apps.cli.chat --backend hermes --message "Use the approved calculator to evaluate 2+2."
```

### Docker API/worker

Windows executables cannot run inside Linux containers. The optional overlay
builds a separate Linux runtime and supplies Linux paths:

```powershell
docker compose -f docker-compose.yml -f docker-compose.hermes.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.hermes.yml up --build -d api worker
```

Set enabled/allowlist values in `.env`; image defaults supply runtime paths and
`/workspace`. Host-only runtime settings are not forwarded by this overlay.
Keep host and Docker configurations distinct when switching modes. Non-default
Hermes timeout/iteration settings require explicit environment overrides in both
Compose services; arbitrary `.env` keys are not automatically forwarded.

For hosted + Hermes, combine base, hosted and Hermes files in that order and add
`.env.supabase`. Approved text fixtures go under
`/workspace/<namespace UUID>/<application agent UUID>/` in the shared named
volume, readable by the container user. Arithmetic needs no fixture file.

Only bounded arithmetic and scoped read-only UTF-8 `.txt` files up to 8 KiB are
exposed. There is no arbitrary shell/network/write access. Hermes `retain:false`
remains rejected. Linux packaging is prepared but **build/start was not verified**
in the recorded pass because Docker was unavailable; host pinned-engine tests passed.

Optional actual-engine/scripted-model tests after host installation:

```powershell
$env:COOKIEAI_HERMES_PYTHON=(Resolve-Path .hermes-runtime/venv/Scripts/python.exe).Path
$env:COOKIEAI_HERMES_SOURCE=(Resolve-Path .hermes-runtime/source/hermes-agent-1f6efd6eb0ba6b573c73c96d14dff1be4454823d).Path
.\.venv\Scripts\python.exe -m pytest tests/integration/test_hermes_execution.py tests/integration/test_autonomy.py tests/integration/test_contrastive.py -q
Remove-Item Env:COOKIEAI_HERMES_PYTHON
Remove-Item Env:COOKIEAI_HERMES_SOURCE
```

Recorded: 27 passed, with scripted model responses rather than live-provider
quality evidence. See [Hermes notes](hermes-integration.md) and
[autonomy contracts](autonomy-operations.md).

## 12. Optional approved autonomous tasks

Requires schema 0019, a running worker and an explicitly approved application
agent. Deterministic execution does not require Hermes. Set in `.env`, then
recreate Docker API/worker or restart both host processes:

```dotenv
MEMORY_AUTONOMY_ENABLED=true
MEMORY_AUTONOMY_ALLOWED_AGENTS=["REPLACE_WITH_APPLICATION_AGENT_UUID"]
MEMORY_AUTONOMY_INTERVAL_SECONDS=30
MEMORY_AUTONOMY_BATCH_SIZE=20
MEMORY_AUTONOMY_DAILY_TOOL_CALLS=100
MEMORY_AUTONOMY_DAILY_MODEL_CALLS=50
```

With section 8's authenticated headers, approve this synthetic arithmetic task:

```powershell
$cookieGoalBody = @{ title = 'Onboarding arithmetic verification'; status = 'ACTIVE' } | ConvertTo-Json
$cookieGoal = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/goals -Headers $cookieHeaders -ContentType 'application/json' -Body $cookieGoalBody
$cookieTaskBody = @{
    goal_id = $cookieGoal.goal_id
    objective = 'Check the approved arithmetic result'
    idempotency_key = [guid]::NewGuid().ToString()
    backend = 'deterministic'
    complete_goal_on_success = $true
    allowed_tools = @('cookieai_calculate')
    steps = @(@{ tool = 'cookieai_calculate'; arguments = @{ expression = '2+2' } })
    verifier = @{ kind = 'DECIMAL_RESULT'; step_index = 0; expected = '4' }
    max_runs = 1
    max_tool_calls = 1
    max_model_calls = 0
    evidence_origin = 'SYNTHETIC'
} | ConvertTo-Json -Depth 8
$cookieTask = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/tasks -Headers $cookieHeaders -ContentType 'application/json' -Body $cookieTaskBody
$cookieTask.task_id
```

After a scheduler interval plus queue time:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/tasks/$($cookieTask.task_id)" -Headers $cookieHeaders
Invoke-RestMethod -Uri http://127.0.0.1:8000/v1/tasks/status -Headers $cookieHeaders
```

Expect COMPLETED, PASS verification in the latest run and an explicitly closed
goal. A model narrative cannot certify success. Synthetic evidence cannot
activate real-world procedures. This is a bounded fixture, not general autonomy.

## 13. Daily operation, updates and backups

For the recommended local stack:

```powershell
docker compose up -d
docker compose ps -a
docker compose logs --tail 100 api worker
docker compose logs -f worker
```

Ctrl+C stops log following, not containers. `docker compose stop` pauses services.
`docker compose down` removes containers/networks but normally preserves named
volumes. **Do not add `-v`** unless deliberately deleting local database/Redis
data. Identity/config files are outside these volumes and need secure preservation.

Images copy source rather than mounting it live. After pulling code or changing
copied tokenizer/config artifacts, rebuild. Review migrations and take a backup
before upgrading existing data; `up` starts the migration dependency. From a
clean working tree, the update sequence is:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
docker compose up --build -d api worker
```

Changing `.env` usually requires recreating containers with `up -d`; `restart`
alone does not reload their environment. Use all chosen overlay flags consistently.

For the **local** PostgreSQL backup/isolated restore drill:

```powershell
.\.venv\Scripts\python.exe -m scripts.backup --restore-drill
```

It writes a dump under ignored `backups/`, restores into a new database, compares
memory counts and writes `docs/backup-drill-results.json`. It targets Compose's
local `postgres`, not Supabase. Dumps are private and **not encrypted** by this
script. This is not scheduled backup/retention certification; hosted encrypted
backups, alerts and restore policy require a reviewed deployment plan. Do not
accidentally publish generated private dumps or overwrite reports without intent.

After reboot, start Docker Desktop; enable its approved startup/login behavior
as needed. API/worker use `restart: unless-stopped`. A powered-off PC cannot run
this stack; independent hosting requires a separate target.

## 14. Troubleshooting

| Problem | Check / corrective action |
|---|---|
| Git/Python/Docker not found | Finish installation and reopen terminal; check PATH and interpreter selection |
| Docker Client only / missing engine pipe | Start Desktop, use Linux/WSL 2 backend, verify virtualization and `docker info` |
| PostgreSQL init script reports `^M`/bad interpreter | Ensure `docker/init-app-role.sh` has LF line endings in the checkout; Windows CRLF conversion can break shell initialization. Inspect the failed initialization before reusing its volume |
| `!reset` rejected | Update Compose/Desktop; hosted overlay needs newer merge-tag support |
| Credential secret files missing | Bootstrap/provision worker against intended migrated database before starting API/worker |
| `ModuleNotFoundError` | Use project `.venv` interpreter and install lock/editable project from repository root |
| PowerShell activation denied | Activation is unnecessary; use explicit `.venv` executables |
| Port occupied | Stop duplicate host API or change `MEMORY_API_PORT`; DB port changes also require updated host URLs |
| Database refused | Check healthy service, target host/port and local versus container addresses |
| Password fails after `.env` edit | Existing volume/role retains its password; changing variables does not rotate it |
| Missing tables/columns | Verify intended database/schema and Alembic head before startup |
| Permission/RLS denied | Check grants and matching identities; do not use superuser/BYPASSRLS as a workaround |
| 401 | Missing/wrong CookieAI bearer, lost raw token or stale API credential-file state |
| 403 | Agent namespace/object/scope grant or optional execution allowlist denies access |
| 422 | Check UUID/session/purpose headers, payload fields and current OpenAPI; model output may also fail validation |
| Liveness passes, requests fail | Check authenticated storage/status, Redis and provider paths; liveness is process-only |
| Turn remains queued | Worker missing/wrong context, Redis outage, failed job or provider backoff; inspect turn/job IDs and logs |
| Provider 502/429/quota error | Check endpoint/key/model access and quotas; explicit embedding endpoint requires its explicit key |
| Bad/empty embedding recall | Verify exact model/version/dimensions, NVIDIA input_type and prefixes; incompatible spaces cannot mix |
| Supabase tenant/user not found | Copy exact session-pooler host/port/username/project suffix; check URL encoding and IPv4/IPv6 |
| Tokenizer absent in image | Fetch before build, use container-visible path and rebuild |
| Hermes rejected/bad path | Match API/worker enablement/allowlist and choose correct host/Linux paths |
| Task UNCERTAIN | Inspect actual state/journal; reconcile before new approval rather than blindly replaying |
| Worker unhealthy | Inspect actual progress/stalls, Redis and provider/queue state; heartbeat alone is insufficient |

When asking for help, share redacted errors, versions, service states and request
IDs. Never share `.env`, bearer tokens, passwords or provider keys. Full
`docker compose config` output can expand secrets; use `config --quiet` to validate.

## 15. macOS/Linux equivalents

Use [Docker Desktop](https://docs.docker.com/desktop/) on macOS or a supported
Docker Engine + Compose plugin on Linux. WSL is Windows-only. Install Git and
Python 3.12 through supported platform installers, then:

```bash
git clone https://github.com/AviralDeshratna11/CookieAI.git
cd CookieAI
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
cp .env.example .env
# Edit .env using section 5 before continuing.
docker compose up -d postgres redis
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m apps.cli.provision_role
.venv/bin/python -m apps.cli.bootstrap
.venv/bin/python -m apps.cli.provision_worker
docker compose up --build -d api worker
```

Wait for database readiness as above and save the token. Replace Windows
interpreter paths with `.venv/bin/python`, Ruff with `.venv/bin/ruff`. Host Hermes
uses `.hermes-runtime/venv/bin/python` and the installer's POSIX source paths.
PowerShell `$env:NAME=...` becomes `export NAME='...'`. Use Swagger or your shell's
JSON/HTTP tools for requests; PowerShell request blocks are not Bash syntax.

## 16. Handoff checklist

- [ ] Compatible Python and Git installed; Docker **Server** available.
- [ ] Lockfile dependencies, editable project and `pip check` complete.
- [ ] Personal `.env` has no unresolved placeholders or copied private credentials.
- [ ] PostgreSQL/Redis ready, schema 0019, restricted application role.
- [ ] Application/worker identities exist in the same intended database.
- [ ] Token saved securely; both ignored identity files present.
- [ ] API/worker running; authenticated write/search and operations checks pass.
- [ ] Model-backed chat checked if that mode is configured.
- [ ] Regression run; skipped external gates understood.
- [ ] Optional Hermes/autonomy enabled only after scoped setup/checks.
- [ ] Backup, update and restart ownership agreed; no secrets/dumps committed.

### Evidence and setup boundary

Paths, commands, schemas and flags were checked against repository code and
official installation/connection documentation. This writing task did not
provision a new computer, create accounts, apply hosted migrations or certify
container builds. Complete the smoke checks on the teammate's actual machine.
All 30 PowerShell blocks passed parser checks; the primary environment block
and sample memory/task requests passed configuration/schema checks. These are
static checks, not execution of the provisioning or installation commands.

Further references: [current status](implemented-and-remaining.md),
[autonomy API/operations](autonomy-operations.md),
[exact validation results](autonomy-validation-results.json),
[architecture](../architecture.md), and [remaining-work ledger](autonomy-execution-ledger.md).
