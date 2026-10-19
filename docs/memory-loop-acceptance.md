# Memory loop: implementation and acceptance

This report supersedes earlier completion-pass summaries for the changes below. Supabase remains the canonical PostgreSQL/pgvector service. NVIDIA Nemotron 3 Ultra handles language generation/extraction/reflection; Nemotron 3 Embed 1B supplies 2048-dimensional memory and entity vectors. API, persistent worker and Redis run in Docker on this PC. No paid fallback, public hosting or GitHub push was enabled.

## Behavior delivered

| Requirement | Implementation | Acceptance evidence | Boundary |
|---|---|---|---|
| Targeted forgetting | `workers/dependencies.py`, repository `hard_delete` | `test_targeted_erasure.py`, `test_agent_loop.py` | Erases affected raw sessions and assistant paraphrases conservatively; legacy raw jobs without trustworthy references are canceled. Unrelated jobs survive. |
| Finding revision | `memory/insights/lifecycle.py`, `reflection/discovery.py` | `test_general_revision.py` | Stable identity, structural lexical dedup, evidence revisions, bounded state history, support/counterevidence and revalidation. Semantic paraphrase merging and administrative supersession remain partial. |
| Deterministic discovery | `reflection/structured.py`, existing tool miner | `test_structured_discovery.py`, `test_reflection.py` | Exact structured recurrence, declared dependencies, entity co-mentions, UTC windows and adjacent event sequences. At most 300 sources/eight changed findings per pass; co-mentions/windows/sequences remain candidates. These are not quantitative causal models or a full graph-motif catalog. |
| Model-assisted discovery | `reflection/discovery.py` | General discovery/revision fixtures and historical live reports | Bounded proposal, counterexample search and separate critic invocation. Three distinct sessions minimum. Separate invocations of the same model do not establish independent scientific validation. Production precision remains unmeasured. |
| Dynamic memory | Existing mutation/temporal engine plus descendant lifecycle invalidation | Temporal/mutation, continuity and revision tests | Corrections preserve history and invalidate dependent context. Editing a source with descendants through PATCH remains deliberately rejected; use explicit correction/supersession instead. |
| Continuity | `context/continuity.py`, migration 0016, periodic `memory.summarize` | `test_continuity.py`, live assistant test | Persistent extractive, attributed snapshots by ACL partition; 200 recent sources, 20 per partition. Stale or inaccessible sources suppress a snapshot until regeneration. This is bounded continuity, not exhaustive lifetime autobiography. |
| Context budgets | `context/budget.py`, pinned public tokenizer manifest | `test_context_budget.py`, live tokenizer loading | Counts serialized context JSON with the Nemotron tokenizer. Chat template, system instructions, user text and output allowance are outside this context budget. Explicit UTF-8 upper-bound fallback if no tokenizer is configured. |
| Actual assistant | `memory/agent/service.py`, API routes, `apps/cli/chat.py` | `test_agent_loop.py`, `assistant-live-results.json` | Durable idempotent turns, current ACL/revision checks, user-only independent ingestion, assistant output retained as attributed history, useful-context feedback and explicit observed outcomes. No external tool execution is invented. |
| Ordered procedures | Episode segmentation and `procedures/service.py` | Procedure tests; real-provider assistant acceptance | At least three matching observed successful sequences, or explicit attributed confirmation. Overlapping experience evidence is deduplicated. Recovery steps require an observed preceding failure. |
| Complex task boundaries | Compatible-model contiguous partitioning of deterministic groups | Source/ordering validators; remaining evaluation below | At most 30 observations per model partition, exact ID coverage/order required. Representative segmentation quality has not been measured. |
| Serendipity | `serendipity/engine.py`, general-finding opportunities | Serendipity/prospective fixtures | Bounded structural, temporal and distant-domain experience neighbors; common successful strategies and counterexamples. Broader graph/analogical families and calibrated novelty remain incomplete. |
| Reliable worker | Bounded dispatch, renewable SQL leases, progress health, queue status | `test_queue_recovery.py`, provider interruption/restart assistant test | Ten-minute queue aging prevents fresh chat from starving older discovery; five bounded retries, quota backoff, inspectable failed jobs, no paid fallback. Sustained hardware/network/database interruption tests remain outstanding. |

Confidence is an evidence-count heuristic, never a calibrated probability. Distinct sessions and stable producer/event IDs prevent common replay inflation; they do not prove that observations are statistically independent. Derived findings, assistant responses and summaries cannot become independent support just because their IDs differ.

## Reproduce the usable flow

From the repository in PowerShell, with the configured API and worker running:

```powershell
.venv\Scripts\python.exe -m apps.cli.chat --message "Remember that Project Cedar uses PostgreSQL."
.venv\Scripts\python.exe -m apps.cli.chat --message "Which database does Project Cedar use?"
```

Each invocation defaults to a new session. For a continuing conversation use `--session <UUID>` on both invocations. Run without `--message` for an interactive conversation. The CLI reads the token privately from `.env` and prints a durable turn ID. A timed-out CLI poll does not delete the submitted observation: inspect the turn/job and poll it later.

Swagger is at `http://127.0.0.1:8010/docs`. Keep the existing authorization/session/purpose headers. New endpoints:

- `POST /v1/agent/turn`: message, idempotency_key, optional context_signature/token_budget/mode. Returns 202 with turn/job IDs; `retain:false` uses a synchronous non-retained response.
- `GET /v1/agent/turn/{turn_id}`: response, referenced memory IDs, stale-context flag, job status and failure class. Restricted to the submitting agent.
- `POST /v1/agent/turn/{turn_id}/feedback`: feedback_id UUID, helpful_memory_ids from that turn, and an optional explicit EpisodeInput. Observed attempts must come from the caller; they are not generated by the assistant.
- `GET /v1/context/continuity`, `POST /v1/context/refresh`: inspect authorized snapshots or queue regeneration.
- `GET /v1/operations/status`: namespace queue counts, oldest queue age, last completion and worker progress/stall status.

Feedback increases successful-use strength, not truth confidence. Replaying a feedback identity is idempotent; changed content conflicts. Up to 100 feedback receipts are retained per turn, with further new feedback rejected explicitly.

## Reproducible bounded provider acceptance

`test_live_nvidia_assistant_outcome_and_later_procedure` in `tests/integration/test_postgres.py` uses a generated, isolated local PostgreSQL schema and real configured NVIDIA endpoints. It extracts the Cedar fact, generates an assistant recall response in a new session, records three explicitly labeled synthetic recovery outcomes, executes the worker experience handler, builds continuity, and generates a later response with the learned ordered procedure supplied as context. The isolated schema is removed afterward. It never drains the live user queue.

Enable only this test with `MEMORY_LIVE_ACCEPTANCE=1` and point `MEMORY_TEST_DATABASE_URL` to the local rollback/test PostgreSQL administrative URL. Keep `.env.cloud` private. The ordinary suite skips this real-provider test intentionally. The report records only models, dimensions and pass/fail flags; it excludes credentials and private content.

## Migration and rollback

Migrations 0015ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“0017 add job dependencies, continuity/turn tables with forced namespace RLS, and job start/finish times. `scripts.upgrade_memory_runtime` takes a private hosted pg_dump first, upgrades inside one PostgreSQL transaction, checks canonical ID count/digest, grants only the new application tables to the restricted role and revokes Supabase public API roles. Existing projections and IDs are not migrated or re-embedded.

Stop API/worker writers for the backup/upgrade window. A failed transaction leaves the old schema intact. Retain the preceding image and local rollback volume. Before new tables are used, rollback can downgrade 0017/0016/0015 after stopping writers; after durable new turns/snapshots exist, preserve/export them before a destructive schema downgrade. The private dump is a separate disaster-recovery path and is not automatically restored over live data.

Active-store forgetting does not erase historical backups, database provider snapshots or logs outside the application. The current hosted dump passed an actual restore drill into a fresh isolated local PostgreSQL database (126 canonical records), removed after verification. Dumps remain unencrypted and unscheduled; encrypted off-host retention and restore policy remain outstanding. The archived public-schema creation entry is skipped only in the isolated drill so pgvector can be preinstalled in its original public schema.

## Remaining requirements and acceptance gaps

The 108-section/1,054-clause requirement inventory remains applicable and deliberately unverified where no clause-specific evidence exists. The following work has not been represented as completed:

- Full semantic finding merge/supersession, complete graph motifs, quantitative anomaly/dependency miners, and representative relation precision/false-association evaluation.
- Ambiguous entity/pronoun identity resolution beyond conservative exact-name linking; same names can still be ambiguous. No permanent vector-only identity merge is enabled.
- Representative multi-turn extraction, segmentation and procedure generalization evaluation; calibrated confidence is not implemented.
- Large-corpus indexed lexical/graph retrieval, diverse-query latency, filtered ANN recall, sustained saturation and service/database failure drills. Historical latency exceeds the master 500 ms target.
- Fully automatic organization membership/admin policy, cross-user federation/consent and required modality pipelines. Existing tenant policy overrides and namespace ACLs remain operational but do not establish these enterprise capabilities.
- Managed secrets/rotation, encrypted scheduled off-host backups/restore drills, monitoring alert destinations and historical backup erasure policy. These need concrete operational destinations/retention decisions.
- Always-on hosting independent of this PC and public HTTPS. The selected deployment is local Docker; this report makes no 24/7 hosting claim.

Core functionality has executable evidence; full master-specification compliance remains **partial**, with unresolved clauses retained in the matrix. No public deployment or GitHub push was performed for this implementation request.

Operational evidence: [runtime upgrade](runtime-upgrade-results.json), [client TLS/grants/RLS](runtime-security-results.json), [hosted restore drill](hosted-backup-results.json), [running assistant and token budget](runtime-loop-results.json). Supabase advisory checks were unavailable because the connected account returned permission denied; direct SQL checks passed. A rollback image from the preceding committed source is retained locally as `cookieai-runtime:before-memory-loop`.

Final regression: **121 passed** on Linux Python 3.12 with PostgreSQL/Redis enabled, one intentionally skipped real-provider test. Windows Python 3.11 passed 120 before the final HTTP-contract fixture was added. Ruff checks, formatting and whitespace validation pass. The separately enabled real-provider acceptance result is recorded in assistant-live-results.json. The running hosted-backed context build passed at 7,082/8,000 model tokens in 18.828 seconds on a cold query. This is a single context-assembly measurement, not a capacity benchmark or compliance with the master latency target.

The final bounded real NVIDIA rerun passed in 155.85 seconds. The final Docker images are running, the worker is healthy, and the final status check reported no pending backlog. No code was pushed to GitHub.
