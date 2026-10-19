# Configured local demo

The API runs at http://127.0.0.1:8010 with interactive API documentation at http://127.0.0.1:8010/docs. PostgreSQL/pgvector is hosted in Supabase; Redis, the API and background worker run in Docker on this PC. Extraction and reflection use `nvidia/nemotron-3-ultra-550b-a55b` directly through NVIDIA's API. Embeddings use `nvidia/nemotron-3-embed-1b` directly through NVIDIA. Ollama is no longer required. See [current cloud connections](cloud-services.md).

All 44 application tables were migrated and verified, preserving 125 memory records. API and worker now connect over TLS through the Supabase Session pooler. The local PostgreSQL volume remains a rollback snapshot; see [Supabase migration status](supabase-migration.md). Hosted URLs and credentials are in ignored `.env.supabase`, while `.env` retains local URLs for direct CLI/test administration.

The API port and bootstrap token remain in ignored `.env`. Active model overrides and keys are in ignored `.env.cloud`:

```dotenv
MEMORY_API_PORT=8010
MEMORY_PROVIDER_BASE_URL=https://integrate.api.nvidia.com/v1
MEMORY_EXTRACTION_MODEL=nvidia/nemotron-3-ultra-550b-a55b
MEMORY_EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b
MEMORY_EMBEDDING_DIMENSIONS=2048
MEMORY_EMBEDDING_INPUT_TYPE_MODE=nvidia
MEMORY_EXTRACTION_RESPONSE_FORMAT=prompt_json
MEMORY_REQUEST_TIMEOUT_SECONDS=180
```

The HTTPS URL works from Docker and Windows. The adapter includes the JSON schema in the prompt and validates the response and source attribution before writing. Invalid output is rejected. No paid fallback has been configured; free developer access remains subject to NVIDIA's limits.

Both memory and entity projections now use 2048-dimensional Nemotron cloud embeddings. All 125 memory IDs were preserved in an atomic five-namespace cutover. A separate read/write service agent runs the persistent Docker worker. Reflection uses real Nemotron proposal/critic calls; they use the same model in separate invocations, not independent model weights. See [completion status](completion-status.md) for the remaining master requirements.

## Try it

In `/docs`, click **Authorize** and paste the value of `MEMORY_LOCAL_TEST_TOKEN` from the ignored `.env`. Keep that token private. Each protected endpoint also needs `X-Session-ID` (generate one with `[guid]::NewGuid()` in PowerShell) and an `X-Purpose` such as `manual testing`.

1. Call `POST /v1/memory/remember` with the JSON below. Use a new idempotency key for each distinct request. `infer` invokes Nemotron; `raw` stores the observation directly.
2. Change `X-Session-ID` and call `POST /v1/memory/search` with `{"query":"Aurora PostgreSQL database","score_threshold":0}`. This demonstrates persistence across sessions.
3. Call `POST /v1/context/build` with `{"query":"Aurora PostgreSQL database"}` to inspect the assembled context packet.
4. Explore the documented entity, goal, episode, experience, procedure, explanation, correction, export and deletion endpoints. Compile and background features have evidence and worker prerequisites described in their schemas and the README.

```json
{
  "messages": [
    {"role": "user", "content": "Project Aurora uses PostgreSQL as its primary database."}
  ],
  "mode": "infer",
  "remember_explicitly": true,
  "idempotency_key": "manual-aurora-1"
}
```

Run the same synthetic end-to-end check automatically from the project directory:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_running
```

It calls the real cloud model, writes a synthetic Aurora fact, checks retrieval in a new session, and checks context composition. It reads the token without printing it. Run the full regression suite using the test database/Redis settings under **Verify** in the README; those tests use controlled model doubles, separately from this live model check.

## Restart

Keep Docker Desktop running, then run:

```powershell
docker compose --env-file .env --env-file .env.supabase --env-file .env.cloud -f docker-compose.yml -f docker-compose.hosted.yml up -d redis api worker
```

After changing Python code, add `--build` to that command. Keep both Compose files and all three env files: the base file alone points back to the local database, and omitting `.env.cloud` restores old model settings. To stop these project containers, use `docker compose stop`. The database volumes remain available for rollback. Do not use `down -v` to restart: that removes the database volumes.

To check the hosted connection and migrated API behavior without creating or deleting memories:

```powershell
.\.venv\Scripts\python.exe -m apps.cli.check_hosted
.\.venv\Scripts\python.exe -m scripts.verify_hosted
```

The existing deletion endpoint clears the namespace's job queue as part of privacy cleanup. The migration smoke test verified deletion and restored pre-test job history afterward; queue preservation on targeted deletion remains a follow-up issue.

## Observe background discovery

```powershell
docker compose ps
docker compose logs --tail 100 worker
```

The worker should be healthy. Logs show job IDs, queue names and completion/failure, without logging stored memory text. In `/docs`, authorize as above and inspect:

- `GET /v1/insights?include_candidates=true`: accepted findings and candidates, evidence IDs, uncertainty and critic results.
- `GET /v1/jobs`: queue state, retry counts and redacted failures.
- `POST /v1/reflection/run?background=true`: queue a bounded discovery run without blocking the API request.
- `POST /v1/jobs/{job_id}/retry`: retry a failed job after fixing its cause.
- `GET /v1/prospective`: inspect visible future opportunities.
- `POST /v1/prospective/activate`: match context, entity/event text or due times.
- `PATCH /v1/prospective/{id}`: acknowledge, dismiss or snooze a reminder and record whether it helped.

`POST /v1/context/build` includes matching prospective previews. These read-only previews do not acknowledge the reminder. Use activation/feedback endpoints to record state changes. Accepted tool/configuration findings create evidence-linked future opportunities automatically. Candidate findings remain available for review, expire after the configured retention interval, and do not enter ordinary factual recall.

Reflection runs every 600 seconds, serendipity every 3,600 seconds, consolidation/decay daily and DREAMER weekly by default. Intervals are configurable through the Compose environment. The worker also processes committed episode events.

## Run live model checks

```powershell
.\.venv\Scripts\python.exe -m scripts.acceptance_live
.\.venv\Scripts\python.exe -m scripts.evaluate_discovery
```

These scripts store explicitly labeled synthetic observations in your local namespace and invoke real models, so they take time and consume model usage. They write reports to `docs/live-acceptance-results.json` and `docs/general-discovery-results.json`. The first checks semantic paraphrases, automatic tool-pattern discovery, new-session context, prospective activation and unauthenticated denial. The second queues a general recurring-choice discovery evaluation. A rejected/absent pattern is a possible model outcome and must be reported rather than relabeled as success.

## Change the embedding model safely

Stop writers before an offline cutover:

```powershell
docker compose stop api worker
.\.venv\Scripts\python.exe -m scripts.backup_hosted
# Update target embedding settings in ignored .env.cloud before the next step.
.\.venv\Scripts\python.exe -m scripts.cutover_cloud_embeddings --offline-confirmed
docker compose --env-file .env --env-file .env.supabase --env-file .env.cloud -f docker-compose.yml -f docker-compose.hosted.yml up -d api worker
```

Set the target model/version/dimensions and matching input format in `.env.cloud` before reindexing, but keep writers stopped until it commits. The cutover prepares bounded API batches outside the transaction, checks the canonical snapshot did not change, and commits all authorized namespaces and both projection stores together. Its private vector cache and backups are ignored by Git and Docker builds. Equal dimensions cannot make two models' vector spaces compatible.

For a fresh setup, bootstrap API credentials as in the README, then run `.\.venv\Scripts\python.exe -m apps.cli.provision_worker` before starting the worker. The ignored `config/worker-context.json` contains its separate identity; do not commit it. The worker has no delete grant.

## Backup and restore drill

Back up the active Supabase application's public schema:

```powershell
.\.venv\Scripts\python.exe -m scripts.backup_hosted
```

This uses the local PostgreSQL container's tools, saves a private archive under ignored `backups/`, and verifies its archive listing. It is a manual backup, not scheduled encrypted off-host retention or a full hosted restore drill.

The command below only drills the old local rollback database:

```powershell
.\.venv\Scripts\python.exe -m scripts.backup --restore-drill
```

This creates a local dump under ignored `backups/` and restores into a fresh `memory_restore_*` database. It does not overwrite the live database. For a stable count comparison, stop API/worker writers during the drill, then restart them. The dump contains private data and is not encrypted by this command. Encryption and off-host retention are separate operational controls.

## Verification on 2026-10-19

Direct NVIDIA chat and embedding endpoints returned HTTP 200. Real Nemotron inferred ingestion stored the synthetic Aurora fact; new-session recall and context composition passed. All 125 original memory IDs and six entity projections were migrated to 2048-dimensional cloud embeddings across five namespaces atomically. The Windows regression suite passes all 104 tests with local PostgreSQL/Redis acceptance gates, and Ruff checks pass. The earlier pinned Docker suite passed 92 tests; the expanded 104-test suite has not been rerun inside Docker. Live results are in `cloud-provider-results.json`, `cloud-embedding-cutover-results.json` and `supabase-read-results.json`. These checks do not certify production readiness or exhaustive model reliability.
