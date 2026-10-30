# Persistent Agent Memory System

The workspace opens directly into chat. A top-right **Debug** inspector exposes sessions, memory, sharing, retrieval and context transfer. See the [chat workspace guide](docs/chat-workspace.md) for the independent Nemotron route, private API/worker configuration and verification limits.

**New teammate?** Follow the [complete setup from scratch](docs/teammate-setup-from-scratch.md)
for installations, Docker, required files, credentials, migrations, startup,
verification, troubleshooting and optional Hermes/autonomy.

Detailed current project status: [what is implemented, verified, partial and still left](docs/project-status-and-roadmap.md), prepared 20 October 2026.

Experimental opt-in execution: [Hermes setup, evidence and limits](docs/hermes-integration.md).
Current implementation work and remaining requirements: [implementation ledger](docs/implementation-ledger.md).

Current memory/assistant implementation and test instructions: [memory loop acceptance](docs/memory-loop-acceptance.md). The full master specification remains partially unverified; see the residual-gap list in that report.


For this PC's configured Supabase database and direct NVIDIA Nemotron APIs, use [running instructions](docs/running-locally.md). Its startup command includes `.env.supabase` and `.env.cloud`; the generic local setup below uses local database/model defaults.

A runnable Python backend built from the complete MEM0 guide and overriding master specification. It preserves main memory vectors, entity vectors and relational state in PostgreSQL/pgvector, with Redis working references and event distribution.

The implementation covers atomic extraction and rolling context; hybrid recall and entities; temporal updates; episodes, structural experiences and conditional procedures; goals and context transfer; graph association; evidence-backed reflection and serendipity; decay, clusters and prospective triggers; provenance and deletion. Durable workers operate outside conversation turns. Source data, statements, inferences and correlations retain distinct labels.

Durable source evidence is stored independently from the ten-message working buffer. Forgetting purges raw source-session content as well as dependent memory projections; a background job cannot restore input after cancellation.

[Architecture](architecture.md) contains the requested 23-part design. See [diagrams](docs/diagrams.md), [phase reports](docs/phase-ledger.md), [verification](docs/verification.md) and ADRs for evidence and limits. This is an executable initial implementation, not production certification.

## Start locally

Containers use Python 3.12. Development tests also support the installed Python 3.11.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[test]'
Copy-Item .env.example .env
docker compose up -d postgres redis
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m apps.cli.provision_role
.\.venv\Scripts\python -m apps.cli.bootstrap
.\.venv\Scripts\python -m apps.cli.provision_worker
.\.venv\Scripts\uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

PostgreSQL binds to localhost:55432; Redis uses localhost:6379. The API uses memory_app, which cannot bypass RLS. Migrations and bootstrap use MEMORY_MIGRATION_DATABASE_URL separately. Fresh volumes initialize the application role automatically; provision_role handles an existing development volume. Use a non-superuser connection for the deployed API.

Bootstrap prints a bearer token once and saves only its digest in ignored config/credentials.json. Requests require Authorization: Bearer <token>, X-Session-ID: <uuid>, and X-Purpose. Credentials bind user, agent, namespace and optional projects server-side. OpenAPI is served at /docs and /openapi.json; a snapshot is in docs/openapi.json. After bootstrap and worker provisioning, run `docker compose up --build -d api worker`. For Docker, set the provider URL to `http://host.docker.internal:11434/v1`; a host Python process uses localhost. Pull the configured embedding model and sign in to Ollama for the cloud generation model before invoking them.

## Models and policy

Set MEMORY_EMBEDDING_BACKEND=compatible and configure the model ID, version, dimensions, provider endpoint/key and extraction model. OpenAI-compatible hosted or local endpoints are supported. Extraction defaults to provider-enforced JSON schema; MEMORY_EXTRACTION_RESPONSE_FORMAT=prompt_json instead includes the schema in the prompt and validates the returned JSON locally. Models are not downloaded automatically. The hash-test backend is a deterministic lexical test double and does not establish natural-language semantic quality. Recall checks model/version/dimensions; reindex jobs rebuild projections after a deliberate model change.

For the configured Nemotron/Ollama demo and interactive testing, see [running locally](docs/running-locally.md).

config/memory.yaml supplies typed policy. MEMORY_<KEY> environment variables and administrator-managed tenant_policies override supported settings. Stored content and model proposals cannot change authorization. All twelve prompt resources are versioned.

## API and agent integration

```python
from examples.client import MemoryClient

client = MemoryClient("http://localhost:8000", token="your-bootstrap-token")
client.remember(
    [{"role": "user", "content": "Project Alpha uses PostgreSQL."}],
    idempotency_key="alpha-choice-v1",
    mode="raw",
)
hits = client.recall("Alpha PostgreSQL")
client.close()
```

Raw mode stores observations. Inferred mode extracts schema/source-validated atomic candidates. Procedural mode preserves a historical process trace; reusable learned procedures separately require repeated evidence or an attributed confirmation. retain=false stores nothing and invokes no model.

New sessions call /v1/context/build; /v1/context/transfer intersects sender/receiver permissions. Structured events enter /v1/episodes; experiences and procedures have compile/search APIs with structural fingerprints. Goals, entities, insights, mutation/correction, pinning, explanations, export/deletion and session completion also have REST contracts. User export/deletion explicitly applies to the authenticated namespace; additional scopes require their own authorization.

memory.tools.AgentTools(memory_service, trusted_context).registry() exposes all sixteen requested tools. examples/agent_integration.py demonstrates automatic recall and post-turn ingestion. Recalled content stays in an untrusted data field.

## Background workers

Run `python -m apps.cli.provision_worker` to create a separate namespace-scoped read/write service agent and the ignored `config/worker-context.json`; start it with `docker compose up -d worker`. The worker has no delete grant. It supports a context-file secret or MEMORY_WORKER_CONTEXT JSON and a configurable MEMORY_REDIS_URL. `docker compose ps` exposes heartbeat health and `docker compose logs worker` shows redacted job progress.

The worker publishes the outbox, consumes Redis events and executes leased jobs. Scheduling covers ten-minute reflection, hourly exploration, daily consolidation/decay and weekly DREAMER. Session completion queues segmentation; structured episodes feed experience/procedure compilation. Workers recheck grants and never execute external actions.

## Verify

```powershell
$env:MEMORY_TEST_DATABASE_URL='postgresql+psycopg://memory:YOUR_LOCAL_POSTGRES_PASSWORD@127.0.0.1:55432/memory?connect_timeout=5'
$env:MEMORY_TEST_REDIS_URL='redis://127.0.0.1:6379/15'
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m examples.benchmark
```

External-store tests create isolated schemas/temporary roles and unique Redis keys. They explicitly skip without the test URLs. Use a disposable database role permitted to create test schemas and roles. Benchmark and smoke-load reports are in docs/benchmark-results.json and docs/load-test-results.json.

## Limits

Evaluate semantic quality using your real models and corpus. Initial retrieval and graph adapters score authorized records exactly; large stores need indexes, pagination and capacity tests. Entity identity is conservative. The initial statistical miner focuses on tool/configuration outcomes. Seasons use an explicit northern-calendar assumption. Context budgets use a conservative byte bound. Complex segmentation, additional pattern miners and cross-user organization federation need domain-specific extensions.

Configure TLS, encrypted storage/backups, secret management, retention and distributed ingress rate limits for deployment. Development passwords are local defaults. At-rest encryption and sustained production capacity have not been certified by local tests.

## Personal AI workflow

The [Personal AI implementation guide](docs/personal-ai-implementation.md) covers
the mobile-friendly portal, approved handoff artifacts, conditional skill
contracts, disclosure enforcement, isolated demo and remaining deployment gates.
Run `python -m scripts.personal_demo` for a temporary synthetic loopback demo.
Nebius setup is prepared separately and has not been enabled on the live stack.
