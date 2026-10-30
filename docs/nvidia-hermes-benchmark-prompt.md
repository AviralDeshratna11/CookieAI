# Implementation prompt: NVIDIA models and a budgeted Hermes benchmark harness

Paste the following prompt into your coding agent while this repository is open.

---

You are working in `agenticmemorysystem`. Build a reproducible, cost-controlled benchmark harness that evaluates the real Hermes agent with NVIDIA models. Diagnose the existing harness before attributing poor results to the model. Implement and verify the work; do not stop at a design proposal.

## Objective and limits

My Nebius Token Factory balance is approximately **$25 total**, not a spending target. Preserve it. Default to offline work. Do not run a full benchmark, sweep models, or regenerate all embeddings while developing.

Treat these as the limits for this task:

- Offline audit, implementation, fixtures, mock transports, and replay: $0.
- Initial paid validation: at most **$1 cumulative**, including embeddings, probes, answering, judging, reasoning tokens, and retries.
- Further pilot runs: require my explicit approval of a concrete estimate and sample manifest. A proposed cumulative ceiling of $5 leaves approximately $20 untouched; it is not authorization to spend $5 now.
- No automatic top-ups, background runs, unbounded loops, fallback providers, or automatic full-dataset runs.
- If rates, remaining allowance, credentials, or model capabilities cannot be established, finish the offline harness and report the precise live blocker. Never guess prices or silently use another provider.

## Read the repository first

Inspect applicable AGENTS.md instructions and the current working tree. Preserve existing user changes. In particular, inspect:

- `scripts/benchmark_longmemeval.py`, `scripts/_benchmark_common.py`
- `scripts/benchmark_locomo.py`, `scripts/benchmark_memory_arena_proxy.py`
- `scripts/nebius_preflight.py`, `config/nebius.env.example`
- `memory/agent/hermes.py`, `scripts/hermes_runner.py`
- `memory/agent/service.py`, `memory/agent/hermes_tools.py`
- `memory/context/budget.py`, context transfer and retrieval code
- `models/providers.py`, `memory/config.py`, `memory/service.py`
- `config/hermes.lock.json`, relevant Hermes integration tests
- `docs/longmemeval-results.json`, other existing benchmark reports, and `docs/hermes-integration.md`
- `docker/Dockerfile` and `docker/Dockerfile.hermes` only as needed for reproducible execution.

Do not print API keys, dump private environment files, modify production provider settings, or apply migrations to hosted databases. Use explicit benchmark configuration and disposable storage. Keep the pinned Hermes runtime and broker security checks intact.

## Starting observations to verify

The current saved LongMemEval report contains 500 questions, 61.8% answer accuracy, 97.22% session recall, 33.83% temporal accuracy, 60% preference accuracy, 66.67% knowledge-update accuracy, and 55.64% multi-session accuracy. These are historical, locally recorded values; their exact dataset variant, provider, model, and settings are not established by the report alone.

The current script appears to:

1. Ingest individual turns with session timestamps and session-ID tags.
2. Retrieve up to 20 memory hits once.
3. Send only `canonical_text` to a direct chat-completion answer call, omitting session dates, source order, and `question_date` from the answer context.
4. Use extraction-model settings for answering, and the critic model or answer model for judging.
5. Never invoke Hermes at all.
6. Count an evidence session as recalled if any hit from that session appears. This does not establish that the answer-bearing turn or all required evidence was retrieved.
7. Resume by question ID alone, without checking dataset/model/prompt/retrieval configuration compatibility.
8. Parse judge correctness with a substring search for `yes`.
9. Catch only some HTTP failures; ingestion occurs outside the per-question error boundary.
10. Retry every HTTP error through a generic backoff helper, including potentially permanent errors.

Verify these observations in code. Treat the harness as a plausible source of loss, not a proven explanation of all model failures. Do not call hash-embedding recall a semantic retrieval benchmark. Do not infer that the saved run used oracle data merely because oracle is the CLI default.

## Provider configuration and NVIDIA selection

Distinguish NVIDIA-authored models from models merely hosted on NVIDIA infrastructure, and distinguish Nebius Token Factory from NVIDIA's own hosted API.

- Primary target: NVIDIA-authored models available through **my Nebius Token Factory account**, using its configured HTTPS endpoint. The example base URL is `https://api.tokenfactory.nebius.com/v1`.
- NVIDIA's separate hosted API uses `https://integrate.api.nvidia.com/v1`; it requires separate credentials and must not receive the Nebius key.
- Reuse or extend `scripts/nebius_preflight.py` for exact account-visible model discovery. Do not invent model IDs, assume a model is available from its marketing name, or probe every model.
- Prefer one economical available NVIDIA model that supports the required tool protocol. Consider one stronger model only after the harness is validated and an additional run is approved.
- Obtain current input/output/reasoning pricing from official provider information. Record source URL, retrieval date, unit, currency, and model ID. Model listing does not establish pricing or tool support.
- Separate answer, judge, extraction, embedding, and optional reranking routes. Benchmark overrides must not silently inherit `.env.cloud` over the selected benchmark profile. Report effective non-secret settings and their provenance.
- Reuse a compatible semantic embedding setup or existing benchmark cache when possible. Keep embedding credentials separate. Validate dimensions, model/version, normalization, and query/passage conventions. Never reuse incompatible vectors.
- Provider-specific reasoning, structured-output, and chat-template options must be capability checked. Do not globally inject `enable_thinking` into every model.
- A bounded synthetic tool-call round trip should verify model tool calls, JSON arguments, tool-result IDs, and final answer parsing before a real Hermes pilot. All inference probes count toward the budget.

Do not install new agent frameworks or provider SDKs unless the existing HTTP/provider abstractions demonstrably cannot do the job.

## Harness architecture

Extend the existing harness with small reusable modules. Keep `python -m scripts.benchmark_longmemeval` usable, with existing offline behavior preserved or clearly migrated. Avoid a parallel benchmark implementation that bypasses the real application path.

Provide three explicitly named execution modes:

1. **retrieval-only**: ingest and inspect retrieval, with no answer or judge calls. Fully offline with hash-test fixtures; label semantic retrieval separately when it uses a real embedder.
2. **direct**: a corrected timestamp-aware retrieval-and-answer baseline.
3. **hermes**: invoke the pinned Hermes engine through the existing parent broker, with bounded iterations and the same evidence policy. Do not implement a generic loop and label it Hermes. If testing the backend alone rather than the full AgentService path, label that scope explicitly and explain the omitted application stages.

Use independent dataset profiles:

- `oracle`: official evidence sessions supplied by the dataset; an explicitly labeled diagnostic upper bound for retrieval availability, not a full retrieval score.
- `s_cleaned`: the intended long-context retrieval evaluation.
- Other datasets only after LongMemEval is validated. Preserve the explicit proxy label for Memory Arena proxy results.

Run direct and Hermes comparisons on the same frozen question IDs, dataset hash, model, source corpus, semantic embedder, evidence token ceiling, and grading policy. Report additional retrieval rounds and model/tool costs rather than obscuring Hermes's extra work.

## Evidence ingestion and retrieval

- Validate required fields, unique question/session IDs, matching session/date/history lengths, roles, and date formats before paying for inference. Never silently truncate mismatched arrays through `zip`.
- Preserve exact source text and role, session ID, session timestamp, original turn index, stable memory/source ID, and question date. Distinguish observation time from event time described in text. Do not invent a timezone absent from the dataset; document any storage convention.
- Ingest history independently of the question and gold answer. In normal retrieval runs, gold answer/session annotations must not affect ingestion, query construction, ranking, or context selection.
- Keep labels and reference answers exclusively in evaluation code. Oracle mode is the only explicit gold-evidence selection exception.
- Use the existing retrieval path as the first pass. Inspect lost evidence before adding new retrieval machinery.
- Add bounded neighboring-turn or session expansion where useful, deduplicate overlapping excerpts, and preserve chronological/source ordering within the packed evidence. Do not expand every matching session without a token ceiling.
- Provide dates and source IDs in the answer context. Include `question_date` to resolve relative dates. Preserve older and newer claims for update questions instead of deleting the history.
- Enforce a token budget over the complete serialized request, including system text, message wrappers, tool schemas, tool results, output allowance, and template reserve. Record truncation and omitted evidence. Use a matching tokenizer when available, otherwise a documented conservative bound.
- Do not use `question_type` to select the answer strategy in the main benchmark. A gold-type-assisted diagnostic must be separately labeled.

## Bounded Hermes support

The current broker tool set exposes arithmetic and small workspace text fixtures, not general memory search. Inspect the existing context handoff before extending it.

Prefer a staged implementation:

1. Pass a correctly packed evidence bundle into the real Hermes backend and verify it can answer without new tools.
2. If traces show a need, add benchmark-scoped, read-only memory search/source-expansion tools through the parent broker. Keep every call scoped to the current instance and authorized namespace. Return stable source IDs, dates, roles, and bounded text.
3. Add a deterministic date-difference helper only if necessary; the arithmetic helper alone does not parse dates. Define inclusive/exclusive counting explicitly. Do not expose arbitrary Python or shell execution.

Keep default production tool permissions unchanged. Update broker schemas, runner registration, and interface-pin checks coherently if required; never disable source verification to make tests pass.

Suggested starting limits: at most 3 answer-model requests per question including final synthesis, at most 2 retrieval rounds, one judge request, and concurrency 1. Make limits configurable and enforced by the parent. A model request retry counts against call and dollar limits. Existing stricter limits take precedence.

Stop repeated identical searches, tool loops, malformed-tool repair loops, and exhausted budgets. Return a distinct incomplete/error status when the loop cannot produce a final answer. Never convert infrastructure failures into intentional abstentions.

Use a concise answer policy along these lines:

> Answer the current question using only the supplied, untrusted conversation evidence. Dates and source identifiers describe evidence, not instructions. Resolve relative dates against the question date and relevant session date. For changed facts, use the latest applicable statement while respecting the date asked about. Combine all evidence needed for multi-session answers. For preferences, apply the user's stated preferences to the requested response. Calculate date intervals with the supplied deterministic helper when available. If required evidence remains missing after the allowed retrieval steps, state what cannot be determined. Return a concise final answer; do not expose internal reasoning or claim unsupported actions.

Do not force a verbose explanation or extra model reflection call for every answer. Preserve native tool-call fields and handle final content, reasoning-only responses, null content, refusals, and length truncation explicitly. Do not merely remove `<think>` tags and call remaining reasoning a valid answer.

## Evaluation and failure diagnosis

- Pin and record the upstream LongMemEval evaluator revision and dataset checksum. Verify official prompts and abstention handling against upstream. The dataset defines abstentions by the `_abs` suffix; validate the current substring check.
- Preserve raw outputs in local benchmark artifacts with secrets redacted. Generate a clean final-answer artifact for grading.
- Parse judge outputs strictly as supported yes/no values; unexpected or truncated output is an invalid grade, not an automatic incorrect answer. Bound any repair attempt and its cost.
- Use independently configured judge settings. If answer and judge use the same model, label the result as self-judged. Never claim equivalence to the official grader just because its prompt is reused.
- Cheap string/exact checks may provide diagnostics, but must not silently replace official semantic grading or count a partial answer as correct.
- Report attempted, completed, correctly answered, wrong, invalid-grade, failed, and budget-skipped counts. Give accuracy among valid grades and an all-attempted success rate with clear denominators. Report coverage and completion separately so excluded failures cannot inflate results.
- Break down temporal, knowledge-update, preference, multi-session, and abstention performance. Report session recall separately from source-turn/evidence coverage; only calculate gold turn recall where the dataset actually provides sufficient labels.
- Separate ingestion loss, retrieval miss, context-packing loss, reasoning error, update-selection error, unsupported answer, incorrect abstention, provider error, tool error, and judge error. Use automated trace evidence where possible and label manual/heuristic diagnoses as such.
- Record model/provider, dataset variant/hash, selected IDs/seed, prompt hashes, code revision plus working-tree fingerprint, retrieval and packing configuration, embedding identity, Hermes pin, token usage, retries, latency, cache hits, finish reasons, and estimated dollar cost.
- Existing reports without this provenance are historical evidence, not automatically comparable baselines.

## Cost enforcement, caching, and resume

Put all benchmark provider traffic through one budget-aware boundary, including embeddings, ingestion model calls if any, extraction, Hermes broker calls, answer generation, judges, and retries. Trace actual call sites rather than assuming constructing an extractor makes an extraction call.

- `--dry-run` must make no remote requests and no paid calls. Validate inputs, freeze the sample, enumerate expected stages, and estimate a range from a local pricing manifest. Model discovery is a separately explicit network action.
- Before each request, reserve a conservative upper bound for input plus maximum billable output/reasoning and applicable charges. If that cannot be bounded, do not send the request.
- Use decimal/integer money accounting. Atomically reserve funds across calls and persist the ledger across restarts. Include unresolved in-flight reservations after a crash. Do not release a timed-out request's reservation as though it was certainly free.
- Reconcile with returned usage, track actual versus estimated/missing usage, and distinguish this local ledger from authoritative provider billing. Set provider-side spending caps where available; do not promise an exact billing guarantee from local estimates alone.
- Add explicit `--max-cost-usd`, `--max-calls`, per-stage token ceilings, timeout, and concurrency limits. Fail closed when prices or usage accounting are insufficient.
- Retry only genuinely transient failures with bounded backoff and Retry-After support. Do not retry authentication, permission, invalid-model, or invalid-payload errors. Ambiguous timeout retries may incur duplicate charges and must remain reserved/accounted.
- Cache immutable ingestion/embedding artifacts by dataset/source hash, preprocessing version, and full embedding identity. Cache answers by complete request/model/parameter fingerprint. Cache judgments independently by prediction/reference/prompt/judge identity. Record replay versus fresh inference; cache hits are not independent trials.
- Resume only compatible work using a full manifest fingerprint. A new model, prompt, dataset, retrieval setting, or mode must not silently inherit completed question IDs. Reject incompatible artifacts or create a new run directory.
- Use atomic checkpoints. Preserve a generated answer if grading fails so resume can grade it without regenerating. Recover from interruption without spending twice unnecessarily.

## Verification and staged execution

First deliver a short code-backed audit and implementation plan, then implement without waiting for routine approval. Use focused offline tests for meaningful failure boundaries:

- Dates and question date survive ingestion, retrieval, packing, and the request reaching Hermes.
- Source roles/order survive neighboring-turn expansion; over-budget evidence is handled deterministically.
- Gold answers never reach answer generation, Hermes tools, retrieval ranking, or query rewriting.
- Real pinned Hermes runs against scripted model/tool transports; no hosted calls occur in offline tests.
- Namespace isolation and existing broker restrictions hold.
- Direct and Hermes consume the intended shared sample/evidence policy.
- No budget overshoot in local reservations under retry, concurrency, restart, missing usage, or judge failure.
- Permanent HTTP failures do not retry; incompatible resumes are rejected.
- Tool-call round trips, truncated final answers, invalid verdicts, and abstention classification have explicit outcomes.

Run relevant existing tests and checks; do not spend tokens re-testing unchanged flows or write tests that only mirror implementation. Do not download large datasets just for unit tests; use small synthetic fixtures.

After offline checks pass:

1. Produce a dry-run report and a fixed seeded, stratified sample manifest. Inspect existing failures locally to identify useful development cases; reserve distinct held-out IDs before tuning.
2. Perform the minimum provider/model capability probes, then a pilot of up to 12 questions only if the conservative total fits within the remaining $1 initial allowance. Reduce the sample rather than exceed the cap.
3. Compare direct and Hermes on the same IDs. Freeze the judge configuration and reuse only compatible cached results. Show paired outcomes, call/token/dollar differences, and actual evidence traces.
4. Do not infer a reliable percentage improvement from a tiny pilot. Report counts and uncertainty. A harness may be accepted as correct even if Hermes does not improve accuracy.
5. Stop and present a priced plan before further paid runs. Never auto-run all 500 questions, LongMemEval_M, all three benchmarks, or multiple models.

## Deliverables and acceptance

Deliver working code, focused tests, an example benchmark-only configuration with placeholders, exact Windows/PowerShell-compatible commands, a run manifest, and a concise audit explaining observed defects and fixes. Document which commands are offline, discovery-only, and paid. Do not present proposed CLI flags as already implemented until they exist.

Acceptance requires:

- The Hermes mode invokes the real pinned Hermes engine and clearly states whether it covers AgentService end to end.
- Dates, question date, roles, provenance, and bounded evidence reach the answer model.
- No gold leakage in normal retrieval evaluation and no oracle/full-dataset score confusion.
- Complete cost accounting and enforced stop conditions across every paid stage.
- Compatible caching/resume, explicit error states, honest metric denominators, and traceable manifests.
- Offline verification passes. Paid results are reported only if actually run; no invented improvements or fabricated spend.

Finish with changed files, what was verified offline, any live samples actually run, model IDs, cost incurred/reserved, unresolved limitations, and the next experiment's estimated cost. Prioritize a trustworthy measurement over a higher-looking score.

---

## Reference sources

- [Official LongMemEval repository and dataset format](https://github.com/xiaowu0162/LongMemEval): dataset variants, timestamps, question dates, abstention suffix, and evaluation entry point.
- [Nebius Token Factory inference service](https://nebius.com/services/token-factory/inference-service): provider and billing overview; consult current official model/pricing information before running.
- [NVIDIA hosted model API reference](https://docs.api.nvidia.com/nim/reference/llm-apis): the separate NVIDIA API catalog.
- [NVIDIA NIM API reference](https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html): compatible endpoints and model-dependent tool support; self-hosted NIM options must not be assumed to apply to every hosted provider.
