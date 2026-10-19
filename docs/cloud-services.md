# Current connections and cloud transition

Verified configuration on 2026-10-19:

| Component | Active implementation | Runs where |
|---|---|---|
| Canonical memory, entity projections, audit, jobs, findings | PostgreSQL 17 / pgvector, Supabase session pooler | Supabase |
| Memory and query embeddings | `nvidia/nemotron-3-embed-1b`, 2048 dimensions | Direct NVIDIA API |
| Inferred extraction | `nvidia/nemotron-3-ultra-550b-a55b` | Direct NVIDIA API |
| Reflection proposals and criticism | `nvidia/nemotron-3-ultra-550b-a55b`, separate calls to the same model | Direct NVIDIA API |
| Query rewriting | Local rules | API process on this PC |
| Hybrid retrieval and ranking | SQL/vector/lexical/entity/graph scoring | API on PC + Supabase |
| API and scheduled discovery worker | Docker services | This PC |
| Events, rate limiting and worker heartbeat | Redis | Docker on this PC |

Nemotron 3 Ultra does not execute every API request. Raw storage, retrieval, authorization, context assembly, vector search, and deterministic statistical checks are application/database operations. Nemotron 3 Embed generates embeddings with distinct `input_type=passage` and `input_type=query` requests. Ultra extracts inferred memories and proposes/critiques supported patterns. Models do not have direct database write access: application validation and authorization control persistence.

The worker runs reflection every 600 seconds and serendipity every 3,600 seconds. It has completed both job types against Supabase. Accepted findings retain evidence, counterexamples, uncertainty and provenance; accepted tool findings can create prospective opportunities for later matching. The migration smoke test retrieved one finding and three prospective records. General LLM-assisted discovery is enabled, but the earlier general discovery evaluation accepted no finding. All correlation families and full general-finding revision are not complete; see [completion status](completion-status.md).

## Requested provider policy

Use open models through free access only, primarily Nemotron 3 Ultra. Do not enable paid subscriptions, metered paid fallbacks, or a different paid model. Free hosted access is usage-limited; exhausted allowances must produce a visible failure/retry rather than silently switching to a paid provider.

[NVIDIA's Nemotron 3 Ultra endpoint](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b) currently advertises a free prototype API for `nvidia/nemotron-3-ultra-550b-a55b` at `https://integrate.api.nvidia.com/v1`. [Nemotron 3 Embed 1B](https://build.nvidia.com/nvidia/nemotron-3-embed-1b) also advertises a free endpoint. These are developer endpoints with provider terms and limits; open model weights do not guarantee unlimited hosted inference.

Direct NVIDIA connections are **active**. Live chat and embedding endpoints returned HTTP 200; extraction and critic JSON contracts passed. All 125 canonical memory IDs and six entity projections were migrated across five namespaces in one transaction. See [embedding cutover results](cloud-embedding-cutover-results.json). A private hosted backup was taken before the change. No paid fallback or subscription was configured.

All 104 regression tests passed, including provider credential isolation, query/passage handling, batch order validation, outer transaction rollback and real PostgreSQL 2048-dimensional candidate search. Migration 0014 adds an HNSW half-vector candidate index; stored vectors and final similarity reranking retain full precision. Index availability is not a representative-scale recall/latency certification.

The ignored `.env.cloud` stores the NVIDIA key and active model overrides. Supply it after `.env` and `.env.supabase` when starting containers. Ollama is no longer required by this configured runtime. Real inferred ingestion, new-session recall and context checks passed after deployment; the API still retrieves one finding and three prospective records.

Separate embedding endpoint/key settings have been added and tested:

```dotenv
MEMORY_PROVIDER_BASE_URL=https://integrate.api.nvidia.com/v1
MEMORY_PROVIDER_API_KEY=<LLM key, in ignored configuration only>
MEMORY_EMBEDDING_PROVIDER_BASE_URL=<embedding endpoint>
MEMORY_EMBEDDING_PROVIDER_API_KEY=<embedding key, in ignored configuration only>
```

Blank embedding overrides preserve shared-provider behavior. A separate embedding host never implicitly receives the LLM key. Compose forwards both provider credentials independently.

Before moving embeddings, validate the target API's query/document input format, dimensions, model identity and prefixes. Pause writers and reindex both memory and entity projections atomically using the existing cutover tooling; retain canonical IDs. Equal dimensions alone do not make Nomic and Nemotron embeddings compatible. Resume only after retrieval and rollback checks pass.

The API server, worker and Redis remain on this PC. Moving those services to cloud hosting requires a selected hosting service and its account configuration; changing the model API does not host the application.

```powershell
docker compose --env-file .env --env-file .env.supabase --env-file .env.cloud -f docker-compose.yml -f docker-compose.hosted.yml up -d redis api worker
```
