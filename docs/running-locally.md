# Configured local demo

The API runs at http://127.0.0.1:8010 with interactive API documentation at http://127.0.0.1:8010/docs. PostgreSQL/pgvector and Redis run in Docker. The API currently uses `nemotron-3-ultra:cloud` through the signed-in Ollama daemon for inferred memory extraction. Ollama routes this model to its cloud service; it does not run on the laptop GPU. See the [official model page](https://ollama.com/library/nemotron-3-ultra).

The current extraction settings in the ignored `.env` are:

```dotenv
MEMORY_API_PORT=8010
MEMORY_PROVIDER_BASE_URL=http://host.docker.internal:11434/v1
MEMORY_EXTRACTION_MODEL=nemotron-3-ultra:cloud
MEMORY_EXTRACTION_RESPONSE_FORMAT=prompt_json
MEMORY_REQUEST_TIMEOUT_SECONDS=180
```

The provider URL above is for Docker containers. A Python process running directly on Windows should use `http://127.0.0.1:11434/v1` instead. Ollama cloud [does not currently enforce structured output schemas](https://docs.ollama.com/capabilities/structured-outputs), so the adapter includes the schema in the prompt, then validates the response and source attribution before writing. Invalid output is rejected.

Embeddings currently use the 64-dimensional `hash-test` lexical test double. This setup verifies the real LLM extraction and persistence path; it does not establish semantic retrieval quality. A separate worker service has not been started; scheduled reflection and maintenance require the worker setup in the README.

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

Keep Docker Desktop and Ollama running, then run:

```powershell
docker compose up -d postgres redis api
```

After changing Python code, use `docker compose up -d --build api`. To stop these project containers, use `docker compose stop`. The database volumes remain available for the next start.

## Verification on 2026-10-19

The live inferred ingestion returned HTTP 200 and stored “Project Aurora uses PostgreSQL as its primary database.” New-session retrieval and context composition both passed. The automated suite passed all 82 tests with PostgreSQL and Redis enabled; Ruff checks passed. These checks do not certify production readiness or exhaustive model reliability.
