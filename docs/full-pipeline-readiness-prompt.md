# Implementation prompt: close benchmark gaps and prepare the training pipeline

Paste the prompt below into a coding agent opened at this repository. This is an
implementation specification, not authorization to spend the $25 account balance.

---

You are working in `agenticmemorysystem`. Complete the architecture and implementation needed for trustworthy, full-scale memory-agent evaluation, and prepare a separate, executable path to actual model fine-tuning where the provider supports it. Fix the demonstrated failures before using training as a proposed solution. Implement and test the authorized offline work; do not stop at an architecture document or claim that API inference trains model weights.

## 1. Outcomes and execution boundaries

Produce two explicitly separate workflows:

1. **Evaluation:** data validation → isolated ingestion/indexing → authorized retrieval → evidence packing → direct/Hermes execution → grading → reproducible reports. Prepare this workflow to handle the complete selected LongMemEval dataset, including all 500 IDs when explicitly requested.
2. **Model training:** eligible training data → leakage checks → validated training artifact → supported fine-tuning job → immutable checkpoint → evaluation against the unchanged base model → optional promotion. Training must actually update model weights or adapters; retrieval indexing, agent memory ingestion, and running an answer model are not weight training.

Make evaluation ready first. Implement training data preparation, job planning, supported-provider adapters, and mock-tested orchestration independently. If the requested NVIDIA model has no supported fine-tuning API for this account, report `training_blocked: unsupported_model_or_account` and finish the other work. Do not invent a training endpoint, silently substitute another base model, rent a GPU, or promise an unavailable checkpoint.

**Budget and authority:** the user has approximately $25 in Token Factory credits. Existing authorization covered an initial $1 cumulative pilot; it did not authorize using the rest, uploading training data, launching fine-tuning, or deploying a model. This prompt authorizes implementation and offline verification. Keep further paid inference, training upload/submission, dedicated endpoints, and deployment gated behind review of a concrete plan and explicit approval. Prepare artifacts and estimates before requesting approval. Lack of a training-model choice is not a reason to stop the offline implementation.

Do not run paid probes just because credentials exist. Do not use the previously exposed chat credential in logs, documentation, examples, source, or commit history. Read a privately supplied environment variable only for explicitly authorized network actions. Preserve existing personal/provider settings and production data.

## 2. Repository inspection and baseline

Read applicable AGENTS.md files, inspect the working tree, and preserve unrelated modifications. Do not assume that an untracked benchmark file is disposable. Inspect at least:

- `scripts/benchmark_longmemeval.py`
- `scripts/_longmemeval_harness.py`, `scripts/_benchmark_runtime.py`, `scripts/_benchmark_common.py`
- `scripts/nebius_preflight.py`, `config/benchmark.nebius.example.json`
- `memory/agent/service.py`, `memory/agent/hermes.py`, `scripts/hermes_runner.py`
- `memory/agent/hermes_tools.py`, `memory/autonomy/contracts.py`, broker and execution tests
- `memory/context/budget.py`, context-transfer code, `memory/service.py`, `memory/policy.py`
- retrieval ranking, diversity selection, query rewriting, source retention, entity projections, and authorization
- `models/providers.py`, `memory/config.py`, `config/memory.yaml`
- `config/hermes.lock.json`, `config/longmemeval-evaluator.lock.json`
- `docs/benchmark-live-results.md`, `docs/benchmark-live-validation.json`
- the initial and corrected synthetic reports and `docs/benchmark-live-oracle-results.json`
- `tests/unit/test_benchmark_harness.py` and relevant existing integration tests
- Dockerfiles and dependency locks only where needed for a reproducible runner.

Private cache/report artifacts under `.benchmark-artifacts` may be inspected locally for diagnosis. Never print the contents of `.env.nebius` or dump other environment files. A rotated credential may make live access unavailable; use offline fixtures and replay.

Start with a short, code-backed audit and phased plan. Then implement the offline phases without asking for routine implementation approval.

## 3. Established evidence: preserve it honestly

The recorded initial live work used:

- Answer model: `nvidia/Nemotron-3_5-Lightning`.
- Judge: `nvidia/nemotron-3-super-120b-a12b`.
- Semantic embeddings: `Qwen/Qwen3-Embedding-8B`, 4,096 dimensions.
- Real pinned Hermes backend through its parent broker, excluding the full AgentService path.

The corrected synthetic development cases scored 4/4 for direct and 4/4 for Hermes. The three-question oracle diagnostic scored 1/3 direct and 0/3 Hermes: four wrong answers and one invalid final response across six attempts. These are development/diagnostic observations, not a full benchmark estimate or evidence of improvement.

Recorded cumulative ledger: 83 attempted HTTP requests; $0.00606986 settled estimated cost, $0.00133608 uncertain reservations, $0.00012258 interrupted reservation, total $0.00752852 spent or reserved. Verify current values locally; do not reset or erase earlier charges to create a fresh allowance. Provider billing remains authoritative.

Reproduce these failures without new hosted calls:

1. `9d25d4e0`, multi-session jewelry count: only two of three gold sessions reached generation. Both answer paths abstained incorrectly. Trace where evidence was lost rather than blaming the model alone.
2. `gpt4_1e4a8aeb`, gardening date interval: the relevant April 15 and April 21 session dates and user statements reached generation. Direct predicted 16 and Hermes 14; reference is 6 days, with 7 inclusive accepted. Arithmetic tools alone did not solve calendar reasoning.
3. `35a27287`, preference: direct was judged correct; Hermes produced a stop response with an unmatched closing `</think>` delimiter. The harness correctly rejected it instead of grading reasoning text as a clean final answer.

Retain earlier compatibility fixes: explicit `max_completion_tokens` mapping, optional fingerprinted `reasoning_effort`, conservative reasoning billing, verified embedding dimensions/index ordering, explicit response-byte bounds, and smaller embedding batches. Recommendation requests may propose new options subject to known preferences; the proposed option need not already exist in history.

## 4. Target architecture and ownership

Extend existing abstractions with focused modules, not a replacement agent framework. Make ownership and interfaces explicit:

| Component | Owns | Must not own |
| --- | --- | --- |
| Dataset adapter | Validated source records, splits, stable identities | Retrieval hints derived from gold answers |
| Artifact/index manager | Immutable corpus projections and compatible reuse | Production vectors or cross-question data sharing |
| Retrieval adapter | Scoped candidate search, bounded expansion, trace | Gold-based ranking or unrestricted database reads |
| Evidence packer | Ranked evidence, source order, dates, budget accounting | Silent loss of required metadata |
| Parent broker | Tool authorization, deadlines, model routes and budgets | Model-controlled permissions or unmetered calls |
| Hermes runtime | Bounded execution using supplied tools | Provider credentials, network access or built-in persistence |
| Evaluator | Reference labels, judging, honest denominators | Sending labels to the answer agent |
| Training adapter | Supported job planning/submission/status/checkpoints | Choosing a different base model or increasing spend silently |
| Experiment controller | Frozen plans, manifests, resumable stages and reports | Implicit full runs or automatic model promotion |

Write typed contracts for source records, evidence bundles, tool calls/results, stage outcomes, run plans, cost plans, training datasets/jobs, and checkpoint provenance. Model a crash or timeout explicitly; never encode it as a successful abstention. Keep public CLI behavior coherent and document intentional migrations.

## 5. Retrieval and context: fix the demonstrated loss

Trace each source through ingestion, embedding, candidate generation, ranking, diversity selection, neighboring-turn expansion, application retrieval limits, and final packing. Distinguish `not_a_candidate`, `ranked_out`, `retrieval_budget_excluded`, `expansion_excluded`, and `packing_excluded` where evidence supports those labels.

Investigate these concrete issues:

- The application may enforce an 8,000-token retrieval policy before the harness's separate 12,000-token evidence allowance. Record effective limits at both stages. Do not report “no packing omissions” as proof no earlier evidence was dropped.
- `isolated_settings()` explicitly supplies Settings fields, but `MemoryService.policy()` calls `load_policy()`, which separately reads `config/memory.yaml` and `MEMORY_*` overrides. Make the benchmark's effective policy explicit, isolated, and fingerprinted without changing normal application precedence. Test this instead of assuming environment isolation is complete.
- Long assistant responses can crowd out short answer-bearing user statements. Preserve assistant evidence for assistant-memory questions, but test general source balancing, smaller coherent chunks, neighboring turns, and session diversity without using gold question type in normal inference.
- Current fixed-size chunks and source-ID prefixes may affect embeddings/ranking and repeated-statement deduplication. Preserve exact source text separately from indexing text. Record normalization, chunk offsets and overlap. Maintain distinct provenance for identical statements in different sessions.
- Stable namespace-independent source IDs must not enable cross-instance access. Validate dates/array lengths before generating paid projections.

Use the existing search path first. Add bounded hybrid candidate fusion, query decomposition or query expansion only when an ablation and trace justify it. Any model-assisted rewrite is a metered stage. Cap expansion, avoid repeated identical queries, and deduplicate without deleting conflicting versions or temporal updates.

For multi-session questions, support a small evidence-collection loop that can retrieve missing aspects and expand a selected source/session. Use question content, not gold evidence IDs or reference answers, to guide it. A question should not receive every session merely because it is oracle data.

Enforce budgets over complete serialized requests, including tool definitions, tool observations, system text, message wrappers, maximum completion/reasoning output, and chat-template reserve. Test with long/multilingual turns and many sources. Expose both the conservative UTF-8 bound and any verified matching tokenizer; do not label bytes as exact model tokens.

Compare fixes against frozen baseline traces. Do not declare an improvement solely from increasing context, changing model, or using more calls; report those costs and separate their effects.

## 6. Bounded memory and calendar tools for Hermes

Implement benchmark-scoped read-only tools through the existing parent broker, with validated schemas and source provenance:

- Search within the current authorized instance/namespace.
- Expand a source or fetch bounded neighboring turns from that namespace.
- Compute a date interval from validated dates and explicit counting semantics.

Do not bypass ACLs with an in-process list or give the child database credentials. Opaque IDs from another question must be denied. Bound result bytes/tokens, retrieval rounds, date operations, repeated calls, wall time and total model requests. Keep tool failures distinct from evidence absence.

For dates, separate two tasks:

1. Resolve what event happened and when from the evidence, preserving source IDs and distinguishing session date, event date, and question date.
2. Perform deterministic calendar arithmetic on the resolved dates.

Support ISO dates, leap years, month/year boundaries, signed elapsed days and explicit inclusive counting. If weeks/months are supported, define calendar versus fixed-duration semantics. Avoid guessing years, locations or timezones. A reference to “today” resolves against the relevant session; “now” in the question resolves against question_date. Ambiguous “last Friday” or month-only dates must retain ambiguity unless a documented convention resolves it.

A successful arithmetic call does not prove the selected event dates were correct. Return the resolved dates, source references and counting rule for verification. Do not embed benchmark answers or hard-code the gardening question.

Update tool registration, broker policy, autonomy contracts and tests coherently. Default production tool permissions must not expand. Preserve interface hashes for unchanged upstream Hermes files. If upstream source truly changes, perform the prescribed review/pin update; never simply disable verification or regenerate hashes to hide a mismatch.

## 7. Provider final-answer normalization

Investigate native `content`, `reasoning`, `reasoning_content`, `tool_calls`, refusals and finish reasons for the selected route using existing cached responses. Preserve the original body locally for diagnosis with secrets excluded.

Define a versioned response adapter with explicit states: valid final, valid tool call, reasoning-only, length-truncated, malformed envelope, refusal, mixed reasoning/final, and incomplete execution. Keep final-answer extraction identical in policy across direct and Hermes modes.

Do not fix unmatched `</think>` by deleting tags and grading the remaining reasoning. If the documented model protocol reliably identifies a final segment, extract only that segment and test it against both valid and malformed fixtures. Otherwise preserve an invalid-final outcome, or allow at most one explicitly budgeted repair that consumes the same per-question limits. Report repairs and their costs; never silently retry until a good answer appears.

Validate that requested reasoning mode is supported for the exact model. Honor `max_completion_tokens` at the actual HTTP boundary for every answer, judge, repair and Hermes request. Test that provider wrappers cannot be replaced with an unmetered Provider by timeout adjustment.

## 8. Complete the end-to-end application route

Keep the existing isolated backend comparison as a diagnostic. Add an explicitly named application mode covering the real AgentService submission, context authorization/transfer, Hermes execution, outcome persistence and permitted memory-learning stages where those stages are part of the product behavior.

Inject benchmark-only generators, extractors, embedders and brokers consistently so no stage can accidentally use `.env.cloud` or an unmetered default. Distinguish raw-ingestion evaluation from extraction/summarization evaluation. Report which stages were actually exercised.

Freeze benchmark state at the appropriate evaluation boundary. Evaluation questions, answers, judge labels, repairs and outcomes must not leak into another question's memory or train data. If a longitudinal task intentionally learns between sessions, define those sessions and the scoring boundary explicitly rather than treating unrelated benchmark questions as one user.

Test cancellation, erasure, authorization revocation, process crash, duplicate submission, tool observation persistence and stale context references. Do not enable background learning, reflection or workers without explicit stage configuration and metering.

## 9. Full-dataset execution and reproducibility

The existing live limit of 12 questions and $1 is an initial-pilot policy. Implement a distinct full-run plan and policy, rather than deleting safety checks or telling the operator to use new artifact roots to reset accounting.

- Separate logical experiment ID, execution attempt ID, stage ID and shared billing scope. Direct and Hermes comparisons share a corpus and evidence policy; report extra agent retrieval separately.
- Freeze the selected IDs and split before running. Full evaluation must cover every requested ID exactly once per mode. The current development/held-out sampler must not silently turn “all 500” into only the development portion. Report any previous development exposure.
- Fingerprint dataset bytes/content, corpus preprocessing, effective policy, code/worktree, prompts, embedding identity/dimensions/prefixes, tokenizer/template, runtime pin, answer/judge/repair routes, response adapter and pricing provenance.
- Cache immutable projections independently from answer and grade caches. Rebuild or reindex on incompatibility. Preserve source identity and authorization when reusing embeddings.
- Make long ingestion stages resumable, with per-shard or per-instance checkpoints and atomic writes. Do not regenerate completed embeddings after a judge crash.
- Resume a generated answer directly into grading. Keep valid raw responses written before cost settlement and final checkpointing where needed to avoid duplicate inference after crashes.
- Support bounded concurrency only after sequential correctness. SQLite/API constraints need explicit handling; shared reservations must remain atomic across processes.
- Implement request/run claims or equivalent protection against two processes making the same uncached paid call simultaneously. Recover stale claims without assuming an in-flight request was free.
- Fingerprint and validate reused evidence bundles so they cannot cross question IDs, corpus versions, authorization scopes or answer policies.
- Retain old reports and inspectable failure records. Do not reclassify failed attempts into success by changing code midway through one manifest.

Provide a single sequential controller with plan, validate, index, execute, grade, summarize, status and resume operations if that fits the existing CLI. These are requirements, not existing command claims: document exact commands only after implementation.

## 10. Budget policies and authoritative reconciliation

Keep every paid request under a common ledger: embeddings and entity projections, rewriting/reranking, extraction, answers, Hermes, judging, repairs, retries and training-related API operations. Track the cost of the complete experiment, not just final answer calls.

Use current official model/pricing/capability documentation and account-visible catalogs only when an authorized network step is needed. A listed model does not prove inference or training entitlement. Never assume the $25 inference credits can fund fine-tuning or dedicated capacity.

Preserve the initial ledger and its uncertain reservations. For larger approved work, implement an auditable policy change or child allocation under a shared parent cap that includes prior spend. The present code prohibits increasing an existing ledger; a reviewed migration must preserve rows/history and avoid racing with requests. Do not bypass that rule by replacing the file.

Validate reserves and actual usage for input, cached input, visible completion and reasoning tokens. Missing usage retains the bound and blocks further paid calls where reconciliation is needed. A failed/timeout request may be billable. Retry only bounded transient failures and respect remaining wall time; do not retry permanent account/model/payload errors.

Generate a dry-run estimate from actual selected source sizes, deduplicated vectors, expected batch requests, query-rewrite bounds and calibrated measured prompt sizes, rather than only multiplying 100 hypothetical entity vectors per turn. Show expected cost, conservative upper bound, reused artifacts and assumptions separately. Never present an estimate as a guarantee of provider billing.

Keep at least a user-approved reserve from the $25 balance. Propose a budget after measurement; do not decide to spend the balance because it exists. Training estimates must include preparation/generation, upload/storage where charged, training tokens/epochs, checkpoints/hosting, evaluation and potential duplicate jobs—not only inference token prices.

## 11. Training data and split hygiene

Build an offline training-artifact pipeline using a separate training corpus whose provenance and permitted use are documented. Do not assume public benchmark questions/answers are acceptable training data.

- Mark every already-inspected pilot ID and related source conversations as development-exposed.
- Split by user/conversation/source lineage, not merely question ID. Check overlaps across oracle/S/M variants and overlapping histories. Freeze split and contamination manifests before generating targets.
- Keep benchmark reference answers, gold session labels and judge-generated labels out of inference inputs. Keep final held-out benchmark data out of training examples, retrieval tuning targets, repair examples and teacher-generated demonstrations.
- Support independently authored synthetic tasks for date arithmetic, temporal updates, evidence gathering, preference application, abstention and tool protocol. Vary names, dates, language and distractors; validate deterministic targets. Do not just paraphrase the three exposed questions.
- Use only consented/appropriate data; implement exclusion/redaction and source deletion propagation. Do not upload private cache transcripts merely because they are available locally.
- Version schemas for chat messages, tools, arguments, tool results and final answers. Include assistant targets only where correct and source-supported. Never train on failed/invalid answers as positive examples.
- Exclude private reasoning traces. Prefer clean final answers and verifiable tool trajectories; do not invent hidden reasoning targets by copying leaked `<think>` content.
- Generate a data card, distribution report, dedup report, leakage report, examples preview, token counts and upload-ready artifact matching the chosen provider's verified schema.
- Teacher-generated examples and automated quality filtering are optional, metered stages with their own estimates; do not automatically synthesize a large paid dataset.

Train/dev/test and development-exposed benchmark IDs must remain independently inspectable. Reserve the final held-out set for comparing the frozen base and trained checkpoint after choices are finalized.

## 12. Actual fine-tuning adapter and lifecycle

Implement a provider interface and job state machine with at least: `PLANNED`, `DATA_VALIDATED`, `READY_FOR_APPROVAL`, `SUBMITTING`, `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCEL_REQUESTED`, `CANCELLED`, `UNKNOWN`.

The adapter needs typed operations for capability discovery, dataset validation/upload planning, job creation planning, status/events, cancellation, checkpoint resolution and cost/status reconciliation. Implement real submission only against verified supported APIs and schemas, with tests using mock transports. No live upload or job launch under this prompt.

Before a job is eligible for approval, establish:

1. Exact trainable base model/version and account entitlement. Inference support is insufficient.
2. Fine-tuning method supported for that model: adapter/LoRA or full weights, and allowed hyperparameters.
3. Dataset/message/tool schema and size/token limits.
4. Explicit epochs, batch/learning-rate controls where supported, validation strategy, seed and stopping rules.
5. Training, storage and serving prices, applicable credit restrictions, maximum liability and cancellation behavior.
6. Idempotency/recovery behavior for upload and submission, including ambiguous timeout outcomes.
7. Immutable checkpoint identity, inference route and a tested way to evaluate it without changing production defaults.

Do not treat cancellation acknowledgment as completed cancellation or zero charges. Do not automatically resubmit a job whose submission outcome is unknown. Store job IDs and request fingerprints without storing credentials.

Avoid fine-tuning a model merely to compensate for missing evidence. Demonstrate fixed harness operation first. Begin with a small approved training smoke job only when support and cost are known; a complete training run requires a reviewed dataset, job config and budget. If token credits do not cover the required service, prepare the artifacts and state the external dependency plainly.

## 13. Checkpoint evaluation and promotion

Evaluate base versus trained checkpoint with the same frozen test IDs, effective retrieval/index, context ceiling, tools, response parsing, judge and attempt policy. Also compare the corrected base harness against the historical harness so harness improvements are not attributed to training.

Report no-memory or oracle diagnostics only as separately labeled ablations. Keep oracle and full S/M results separate. Include held-out completion/format validity, tool adherence, temporal accuracy, update handling, preference use, multi-session results, abstention, latency, cost and cost per successful answer.

Report planned, attempted, completed, validly graded, correct, wrong, invalid-final, invalid-grade, infrastructure failure and budget-skipped counts. Provide both valid-grade accuracy and all-attempted success; do not hide invalid outputs by excluding them from the headline. Include paired disagreements and confidence intervals suited to the sample size. Tiny pilot percentages are descriptive, not reliable improvement claims.

Maintain an independently configured grader; label self-judging when applicable. Audit a fixed sample of disagreements, judge errors and abstentions. Deterministic date tests validate mechanics but do not replace semantic benchmark grading.

Promotion is a separate explicit step. Never overwrite production model defaults, start a dedicated endpoint, or deploy automatically because training succeeded. Preserve the base route for rollback and record the acceptance decision.

## 14. Verification and readiness gates

Add meaningful fixtures and focused tests. Reuse the existing runtime and contracts; do not build a mock-only alternate agent and call it Hermes.

Required offline verification includes:

- Reproduce the three exposed failures from recorded sources/cached outputs; explain the stage responsible without claiming all are retrieval failures.
- Positive and negative evidence collection cases with distractors, duplicate text, contradictory dates and multiple sessions; no gold-label input leakage.
- Stable source identity, exact text/role/order/date retention, bounded expansion, and upstream-versus-final packing exclusion reporting.
- Benchmark policy isolation despite hostile ambient `MEMORY_*` values; effective config/policy changes invalidate resume.
- Calendar tests for leap days, reversed dates, month/year boundaries, relative date references, ambiguous years, inclusive counting and unsupported units.
- Cross-namespace tool requests denied; schemas enforced; no child credentials; fixed request/iteration/tool/output/deadline ceilings.
- Native content/reasoning/tool protocol fixtures, unmatched markers, length stops, null content, malformed envelopes, refusals and bounded repair exhaustion.
- Real pinned Hermes against scripted provider/tool responses; full AgentService route against injected offline dependencies.
- Embedding index ordering/dimensions, response byte bounds, batch splits, cache identity and interruption recovery.
- Reservations/retries/restarts/missing usage, concurrent duplicate claims, cap transitions and reconciliation preserve prior spend.
- Full-run selection covers the exact requested ID set once per mode; development exposure and grouped split overlap are detected.
- Training dataset leakage and schema checks, upload/submission planning, all job transitions, duplicate/unknown submission, cancellation, checkpoint loading and base/checkpoint evaluation through mock APIs.

Run appropriate existing checks. Document skipped external checks separately. Do not make every unit test download a model, contact a provider, launch a container, or read credentials.

Use explicit readiness states rather than a single “done” claim:

- **Offline architecture ready:** implementation, contracts, fixtures and regression checks pass.
- **Evaluation ready for paid validation:** frozen held-out pilot, current provider prerequisites, honest cost plan and reproducible commands exist; no paid run implied.
- **Full evaluation ready:** approved pilot demonstrates completion/protocol reliability and controlled evidence handling; the full selected corpus and budget are validated.
- **Training artifacts ready:** separate corpus, schema, leakage/data-card reports and job plan exist.
- **Training ready for submission:** exact model/account capability, approved dataset upload, job configuration and liability cap are established.
- **Checkpoint ready for promotion:** successful job plus frozen held-out comparison meets predefined acceptance criteria and explicit promotion approval is obtained.

Define acceptance thresholds before looking at new held-out outcomes. Do not require a specific benchmark percentage just to declare an engineering pipeline correct, and do not call a poor model production-ready because plumbing tests pass.

## 15. Deliverables and completion report

Deliver working code, versioned example configurations without secrets, typed schemas, focused tests, migration notes, architecture/data-flow documentation, readiness output and exact PowerShell-compatible commands. Organize examples by offline, discovery/network, paid inference, data upload/training and promotion so the operator knows what starts a billable action.

Required reviewable artifacts:

- Audit with code/source references and reproduced failure diagnoses.
- Updated full-run architecture and stage/state ownership.
- Frozen evaluation manifest and cost plan with no network dry run.
- Updated deterministic regression fixtures and offline replay report.
- Training dataset schema and synthetic sample artifact, data card, split/leakage report and validated job-plan artifact.
- Capability report that honestly marks unverified/unsupported model training.
- Base-versus-checkpoint evaluation contract and promotion/rollback plan.
- Clear readiness matrix separating implemented, offline-tested, live-verified and externally blocked capabilities.

Do not fabricate provider access, training jobs, checkpoints, benchmark gains or billing. Do not present newly proposed CLI flags as already working. Unsupported training is an explicit supported outcome of the capability gate, not a reason to leave retrieval and evaluation implementation unfinished.

Finish with changed files, offline verification results, any real network or paid activity actually authorized and performed, cumulative spend/reservations, remaining blockers, and the next concrete approval artifact. Prepare everything necessary to make approval the final step before billable upload, training or a larger evaluation.

---

Repository evidence for this specification:

- [Live diagnostic report](benchmark-live-results.md)
- [Machine-readable findings and cumulative cost](benchmark-live-validation.json)
- [Current harness operation and limits](benchmark-harness.md)
- [Earlier implementation prompt](nvidia-hermes-benchmark-prompt.md)

This prompt itself launches no benchmarks, uploads no data, and submits no training job.
