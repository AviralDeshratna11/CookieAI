# Completion status and acceptance boundaries

Current local extension: [continuous autonomy checkpoint](autonomy-execution-ledger.md).
Approved bounded tasks now run through the existing worker with independent
verification, event subscriptions, quotas and erasure fencing. Default regression
is 139 passed/14 skipped. Source migration head is 0019; no hosted migration was
applied. This supersedes earlier local counts below without closing the remaining
master requirements or certifying current container availability.

Local follow-up from `ba7a5f3`: an opt-in isolated Hermes pilot, durable sanitized
execution observations, full prompt accounting and frontier graph edge queries
are implemented. See [current work and unresolved requirements](implementation-ledger.md)
and [Hermes operating/acceptance boundaries](hermes-integration.md). These changes
do not establish full specification completion or a hosted deployment.

Latest execution update: the assistant recall/outcome/procedure loop passed a bounded real NVIDIA acceptance test against an isolated PostgreSQL schema. Dependency-scoped forgetting, finding revision, continuity, token budgets and worker recovery have new regression coverage. [Current implementation, evidence and residual requirements](memory-loop-acceptance.md) supersedes the older completion-pass details below. Full master-specification acceptance is still partial.


The local Docker pipeline is operational; the entire master specification is not certified complete. The user selected local Docker on this PC as the deployment target. No public deployment or new GitHub push is authorized by the completion request.

Subsequent updates moved PostgreSQL to Supabase and model calls directly to NVIDIA's free developer APIs: Nemotron 3 Ultra for extraction/reflection and Nemotron 3 Embed 1B for 2048-dimensional memory/entity vectors. API, worker and Redis still run locally. All 125 memory IDs survived the five-namespace atomic vector migration, and 104 regression tests pass. See [cloud services](cloud-services.md) for current connections; the earlier Nomic work below describes the preceding implementation stage.

## Implemented during this completion pass

- Replaced the active hash-test projections with 768-dimensional Nomic embeddings. Canonical memories and IDs were preserved. Memory and entity projection cutover is namespace-atomic, resumable, and covered by rollback/retry tests.
- Added a separate read/write service agent, ignored worker context file, persistent Compose worker, configurable schedules, graceful shutdown, health heartbeat, scoped job claiming, unique Redis consumer identities, and renewable SQL leases.
- Connected the tool/configuration reflection pipeline to real Nemotron proposal and critic invocations. Models cannot alter the supplied evidence identities or increase the deterministic verdict. Long model calls run outside namespace write transactions; evidence revisions and the execution lease are checked before persistence.
- Added bounded general source-pattern discovery with separate proposal, counterexample and critic calls. It excludes derived/tool observations from independent direct-source support, requires distinct source sessions, and records bounded search coverage. A distinct session is a useful operational gate, not proof of statistical independence.
- Added inferred prospective opportunities for accepted tool findings, context previews, activation reasons/counts, acknowledgement, dismissal, snoozing, feedback, and repeat suppression. Evidence deletion removes dependent opportunities.
- Excluded unvalidated/rejected/invalidated findings from ordinary recall. Candidate retention defaults to 30 days. Findings preserve source attribution, uncertainty, counterexamples and explicit non-causal labels.
- Added queued reflection runs, job inspection and failed-job retries. Errors expose exception classes rather than source content.
- Added explicit event identities to episode ingestion and stable identities for generated segments; replaying an event cannot inflate its evidence count. Explicit task tags and boundary markers augment session/time segmentation.
- Added SQL-side ACL/validity filtering and bounded vector candidate fetching, a dimension-filtered HNSW index and worker lookup indexes in migration 0013. Lexical and graph scoring still have scale limits.
- Added shared atomic Redis ingress rate limits and pinned Docker dependencies to the committed lock file.
- Added live worker/model acceptance, real semantic paraphrase evaluation, a recurring-choice evaluation, a backup/restore drill, and requirement inventory tooling.

## What remains within the master target

1. Finish the manual requirement-level audit. `requirements-matrix.md` inventories all 108 numbered sections and 1,054 clause groups. Unverified clauses are deliberately marked unverified; generating an inventory is not passing their acceptance tests.
2. Expand deterministic statistical miners beyond tool/configuration failures. General LLM-assisted discovery broadens pattern proposals but does not implement every event-sequence, graph-motif or quantitative correlation analysis. Confidence formulas are conservative heuristics, not calibrated probabilities; causal inference is not implemented.
3. Improve source independence/deduplication across producers and evaluate resolution of ambiguous entities/pronouns. Event IDs prevent replay inflation when producers supply stable identities; different IDs do not prove independent events.
4. Complete general finding deduplication, revision/revalidation after new counterevidence, and a fully typed finding lifecycle. The tool/configuration path revises existing findings; general proposals currently use bounded support-set deduplication and provenance invalidation.
5. Complete all serendipity neighbor families and idle-compute scheduling, and evaluate model-assisted cross-domain analogies. The current serendipity implementation remains primarily structural/rule-based.
6. Complete model-assisted complex task segmentation and richer procedure sequence induction. Explicit task signals now work, but automatic understanding of every task boundary is unproven.
7. Add asynchronous persistent autobiographical summaries and remaining context-budget policy controls. Current context is regenerated from evidence, with a conservative whole-package byte budget.
8. Implement organization membership, cross-user federation, administrative policy provisioning, and associated consent/export/deletion semantics. Same-user authorized agent transfer does not establish these capabilities.
9. Replace remaining full authorized-corpus lexical/graph scans with scalable adapters. Validate filtered ANN recall and index plans on representative datasets, add pagination where missing, and run sustained load/soak/recovery tests.
10. Complete the full evaluation/observability suite: calibrated extraction and correlation precision, false associations, temporal/entity accuracy, long-range analogy, representative latency and utility measurements. Small synthetic fixtures do not establish broad reliability.
11. Complete all-settings tenant overrides, richer operational alerts, credential rotation workflows, and any modality-specific pipelines required beyond artifact references. An interface or artifact URI is not a working image/audio pipeline.

## Production controls outside this local target

Internet-facing HTTPS, host/disk encryption, off-host encrypted backups, managed secrets, production alert destinations, and retention/erasure guarantees for historical backups require a chosen deployment and operational policy. The local backup command produces an unencrypted dump in the ignored `backups/` directory; its existence does not establish encryption at rest. Restore drills use a separate fresh database and never overwrite the live database.

The local services must not be described as production certified. The source specification remains controlling; none of the requirements above have been removed.
