# Supabase migration status

Destination project: `paipjmkfgizkfyajskze` (`https://paipjmkfgizkfyajskze.supabase.co`), supplied by the user. On 2026-10-19, all 44 application tables were copied in a single transaction to PostgreSQL 17.11 / pgvector 0.8.2, preserving IDs and all 125 memory records. Every table's row count and content fingerprint matched. See [migration results](supabase-migration-results.json).

**Cutover completed on 2026-10-19.** The API and worker now use the IPv4 Session pooler at `aws-0-ap-northeast-1.pooler.supabase.com:5432`. Both Windows and Docker connect with TLS. The original local PostgreSQL volume remains a rollback snapshot; Redis, API, worker and Ollama still run on this PC. Credentials are saved in ignored `.env.supabase`.

The hosted restricted login has no superuser or RLS bypass privileges. Unscoped and unrelated-namespace reads return zero memories; the existing authorized namespace returns 123 of the 125 migrated records. Memory and entity vectors are 768-dimensional. Supabase `anon`, `authenticated`, `service_role`, and PUBLIC have no SELECT grants on the application tables. See [security results](supabase-security-results.json).

Before cutover, local writers were paused, a fresh backup was restored successfully into a separate test database, and all 44 staged tables were refreshed atomically. The refresh locked the application tables and verified the staged copy was unchanged before replacing it. Do not rerun either migration script against the live hosted database. The hosted copy now receives application traffic and differs from the frozen local snapshot.

Live checks passed for existing-token authentication, migrated memory retrieval, context composition, one visible correlation finding, three prospective records, and cross-session reads. A temporary API write was confirmed directly in Supabase and then deleted; an invalid token was denied. The worker is healthy and completed a job created after cutover. See [live results](supabase-live-results.json) and [security results](supabase-security-results.json). The full regression suite passed: **98 tests**, using the local isolated test schemas rather than the hosted runtime.

The deletion smoke test exposed existing behavior in `SQLMemoryRepository.hard_delete`: deleting one memory clears all jobs in its namespace. The 190 pre-test job records were restored from the frozen source after verifying all original canonical memory IDs still existed. This behavior remains a follow-up issue; the repeatable verification script below only retrieves data and checks authentication.

Supabase supports [pgvector](https://supabase.com/docs/guides/ai/vector-columns). Use a direct database connection when the local network supports it, or the IPv4-compatible session pooler. The project uses durable database connections and transaction-local namespace settings. Migration/restore commands must not use the transaction pooler. See [Supabase connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Cutover procedure

1. Create the CookieAI project in the selected Supabase organization after checking its actual plan/cost and region. Keep the generated database password in local ignored configuration.
2. Inspect the destination PostgreSQL/pgvector version, extension schema and existing public tables. Refuse to overwrite an existing application schema.
3. Briefly stop the local API and worker so the database snapshot is consistent. Keep PostgreSQL and Redis running.
4. Take a fresh custom-format local backup and record table counts, identity/grant IDs, migration revision and vector-space metadata.
5. Restore only the application's public schema into the new project with original data IDs preserved. Do not restore local ownership or blanket local grants into Supabase's managed schemas.
6. Provision a restricted `memory_app` login, preserve the existing forced RLS policies, and configure the extension search path if needed. Keep migration/admin access separate from application access. Do not grant `anon` or `authenticated` access to the memory tables.
7. Store application and migration URLs with TLS in ignored `.env.supabase` as `MEMORY_HOSTED_DATABASE_URL` and `MEMORY_HOSTED_MIGRATION_DATABASE_URL`. Use SQLAlchemy `postgresql+psycopg://` URLs and URL-encode password characters. No credentials belong in this document or Git.
8. Run `python -m apps.cli.check_hosted`. Verify restricted application access, TLS, migrations, vector dimensions, row counts and provenance/dependency records.
9. Start the API and worker using the hosted override below. Verify health, existing-token authentication, stored-memory retrieval, context composition, a temporary write/delete, worker queues and namespace/RLS denial.
10. Keep the local volume and fresh backup for rollback. Resume normal writes only after the checks pass. Once hosted writes begin, local data is a snapshot; switching back requires reconciling those writes.

## Hosted startup

```powershell
docker compose --env-file .env --env-file .env.supabase --env-file .env.cloud -f docker-compose.yml -f docker-compose.hosted.yml up -d api worker
```

Redis, the API, worker and Ollama continue running on this PC. Only PostgreSQL moves to Supabase. The default Compose file still points at local PostgreSQL; use the hosted command consistently after cutover.

The override removes the migration service's local PostgreSQL dependency and supplies explicit hosted application/admin URLs. Session-pooler usernames include the project suffix for both admin and custom application roles; the passwords remain separate. TLS preflight checks libpq's client connection, because PostgreSQL's `pg_stat_ssl` reports the pooler's upstream session rather than the client's session.

The final verified pre-cutover backup is `backups/memory-20261019T175147Z-f4c516e9.dump` (608,393 bytes). It was restored into a fresh database and contained all 125 source memory records. The original local volume remains intact. `scripts.backup` currently backs up this local database; it does not back up subsequent hosted writes. Use `scripts.backup_hosted` for a manual hosted application archive; encrypted off-host scheduling remains separate.

The migration implementation accepts an externally owned Alembic connection so schema creation, table copy, role provisioning and grants commit together. A real PostgreSQL test verifies rollback removes both schema and copied rows. The hosted preflight and PostgreSQL migration checks passed: 9 tests.

## Repeat verification and rollback

```powershell
.\.venv\Scripts\python.exe -m apps.cli.check_hosted
.\.venv\Scripts\python.exe -m scripts.verify_hosted
docker compose ps
docker compose logs --tail 50 worker
```

The runtime reads hosted connection URLs from `.env.supabase` and direct NVIDIA model overrides from `.env.cloud`. Memory/entity vectors were subsequently migrated to Nemotron 3 Embed 1B (2048 dimensions), with migration 0014 adding its candidate index. See [cloud transition](cloud-services.md). The regular `.env` retains local URLs for direct CLI/test administration. API-based verification uses the running hosted runtime. `python -m scripts.backup_hosted` provides a manual hosted public-schema dump; scheduled encrypted off-host backup controls remain separate.

To return to the local snapshot, stop hosted API/worker first, reconcile or export hosted writes, then use `docker compose up -d api worker` with the base file only. This is a rollback, not the normal restart command. Do not delete either database or its volume.
