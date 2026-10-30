# NVIDIA / Hermes benchmark harness

For the current source-offset preprocessing, scoped memory/calendar tools,
AgentService mode, full-run controller and training lifecycle, see the
[evaluation and training pipeline guide](experiment-pipeline.md). The sections
below describe the initial pilot and retain its historical limits/tool scope.

The LongMemEval entry point now supports offline retrieval, a timestamp-aware
direct baseline, the real pinned Hermes engine, and a paired comparison. All
development and validation for this change uses synthetic data or mock HTTP;
adding credentials does not automatically start a paid run.

## What changed and why

The previous script called a chat-completion answer model directly; it did not
measure Hermes. Its answer prompt discarded the session dates and question date.
Its session-recall metric counted any retrieved turn from a gold session, and its
checkpoint accepted matching question IDs from unrelated configurations. It also
accepted any judge text containing `yes`, retried permanent HTTP failures, and
could lose a generated answer when its judge failed.

Historical saved results (61.8% answer accuracy, 97.22% session recall, 33.83%
temporal accuracy) do not prove whether retrieval, packing, reasoning, or grading
caused a particular failure. Their missing configuration provenance prevents a
controlled comparison with new runs. They have not been overwritten.

The new path uses `MemoryService` for raw ingestion and retrieval. It preserves
source text, role, session date, turn/chunk order, stable source IDs and the
question date; expands a bounded number of neighboring turns; packs ranked
evidence within an explicit token budget; and sorts selected evidence by date.
The same selected evidence is shared by direct and Hermes modes in a comparison.
Gold answers and session annotations are used only after retrieval for metrics
and judging, never for normal retrieval or answering. Dataset question types
control sample stratification and grading, not answer strategy.

The Hermes mode runs `HermesBackend` and `scripts/hermes_runner.py` against the
existing interface pin. Only `cookieai_calculate` is enabled. Production tools,
permissions, provider settings, and source verification are unchanged. The pilot
allows up to three answer-model requests, including retries, one judge request,
and concurrency one. Retrieval is one initial pass, with **no agent-driven search
or date-helper tool added**; traces should justify those extensions first.

This measures **MemoryService + HermesBackend**, not the full AgentService durable
turn, context-transfer, worker, or learning pipeline. An incomplete Hermes run is
an error, not an intentional abstention.

## Offline commands — no API key needed

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_longmemeval --dry-run --run-dir .benchmark-artifacts\plan
.\.venv\Scripts\python.exe -m scripts.benchmark_longmemeval --run-dir .benchmark-artifacts\offline
.\.venv\Scripts\python.exe -m pytest tests\unit\test_benchmark_harness.py -q
```

The default data is `tests/fixtures/longmemeval_synthetic.json`. Hash embeddings
are a lexical plumbing test, not a semantic retrieval score. The real-engine
test runs if the pinned Windows Hermes runtime already exists under
`.hermes-runtime`; otherwise that test is explicitly skipped. It uses scripted
responses and brokered arithmetic, with no hosted inference.

To plan a future comparison while the example profile still has placeholders:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_longmemeval --mode compare --profile config\benchmark.nebius.example.json --dry-run --run-dir .benchmark-artifacts\comparison-plan
```

The dry run writes a sample manifest and reports unresolved pricing/model
configuration. It performs no discovery or inference requests. Its planning
bounds assume uncached calls and deliberately overcount possible entity
embeddings. Request-time reservations remain the enforcement boundary.

## Configure later

```powershell
Copy-Item config\benchmark.nebius.example.json config\benchmark.nebius.local.json
```

The local copy is ignored by Git. Do not put a key in JSON. The harness reads only
the environment variable named by each route's `api_key_env`. It does not load
`.env`, `.env.cloud`, or ambient `MEMORY_*` settings. Set `NEBIUS_API_KEY` privately
in your shell or secret manager when ready; do not paste it into chat.

**Discovery only**, after the key is available:

```powershell
.\.venv\Scripts\python.exe -m scripts.nebius_preflight
```

That existing command lists the account-visible NVIDIA model IDs; it does not
perform inference unless its separate `--inference` flag is used. Do not use that
unmetered inference flag for this budgeted pilot. The harness's `--probe-tools`
performs its own two-request, metered synthetic tool round trip instead.

Fill the answer and judge routes with exact NVIDIA-authored model IDs from your
account catalog. Record current official input/output USD prices per million
tokens, the official source URL, and verification date (within 30 days). Confirm
that `max_tokens` bounds *all* billable completion/reasoning tokens and that the
declared output price includes reasoning before setting those verification
booleans. No default prices or model availability are invented. Unsupported
reasoning parameters and fallback models are not injected.

Answer and judge settings are independent. Using the same provider/model is
explicitly reported as self-judging, even if other route parameters differ.
Strict yes/no parsing and suffix-based abstention classification are documented
deviations from the [pinned upstream evaluator](https://github.com/xiaowu0162/LongMemEval/blob/d6dc8b50a2d9ac0c99485ea28fa5755c62414c34/src/evaluation/evaluate_qa.py).
NVIDIA-judged scores are not official-grader scores.

Real paid oracle/S datasets require `embedding.backend = "compatible"`, matching
dimensions/version/prefix/input-type configuration, and an independent
`embedding.route`. A route has the same base URL, key-variable, model, pricing,
timeout and billing-bound fields as the answer route. The embedding model need
not be NVIDIA-authored. Only the Nebius endpoint is accepted by this initial
paid harness; if the account lacks suitable models/embeddings, report that
blocker rather than switching providers or sending its key to NVIDIA's API.

All embedding calls made by MemoryService, including entity projections and
query rewrites, go through the same metered cache. No extraction model is called
by raw ingestion. Existing production vectors/databases are not reused or changed.
For a provider verified to support embedding arrays, set `batching_verified` to
true and `batch_size` to at most 32. The harness then precomputes bounded batches
of the same source/entity vectors the service needs, avoiding one HTTP request
per ingested turn. Batch requests remain fully metered; partial batches are
cached across interruptions. Keep the default size of one until support is known.

## Paid pilot command — only after configuration is complete

This command makes hosted inference requests, including the tool probe:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_longmemeval --data data\longmemeval_s_cleaned.json --dataset-profile s_cleaned --profile config\benchmark.nebius.local.json --mode compare --live --probe-tools --limit 12 --max-cost-usd 1 --max-calls 100 --run-dir .benchmark-artifacts\pilot-s
```

First run that command with `--dry-run` and inspect its manifest and estimates.
Reduce the sample if it is too costly. Do not download a large dataset just to
test the implementation. Supply the intended cleaned dataset yourself. Use
`--dataset-profile oracle` for oracle data; oracle scores are diagnostic evidence
availability bounds, not full retrieval results. V1 data is expected; this is
not a LongMemEval-V2 reproduction.

`--split development` is the default; `--split heldout` uses the disjoint reserved
split. A fixed seed stratifies by question type and abstention. Tiny buckets may
have no held-out items. No 500-question paid run is enabled: initial live samples
are capped at 12 and each task ledger at $1. A larger pilot requires a separate,
explicitly approved policy change; the $25 account balance is not a target.

## Spending, caching, and interruptions

`.benchmark-artifacts/budget.sqlite3` is shared across run directories by default.
It reserves conservative money and call bounds atomically before **every** paid
HTTP attempt. Input accounting includes serialized requests and a template
reserve. Returned usage settles the reservation; missing usage blocks subsequent
paid calls. Crashed, pending, failed, or timed-out requests keep their reservation.
Unknown transport outcomes are not automatically retried. Only bounded
429/502/503/504 retries are allowed, and they consume new reservations and the
same per-stage request allowance. Authentication and invalid-payload/model errors
do not retry. An existing ledger cannot be reopened with a higher limit.

Keep the same artifact root and ledger throughout this task. Deleting them or
changing `--artifact-root` loses cumulative accounting; this is a local control,
not a provider-enforced account cap. Set a provider-side spending cap where your
account supports one. Actual billing remains authoritative; an incorrect price
manifest or incorrect billing-bound declaration cannot be fixed by a local
estimate. An observed overrun stops later paid requests and retains the measured
cost for reconciliation.

Responses are cached by full route/request fingerprint; the route includes
pricing and embedding identity. Raw completion bodies remain local in the ignored
cache for diagnosis. Cache hits are recorded and are not fresh trials. Source
ingestion is rebuilt in a disposable in-memory SQLite database; embedding HTTP
results, including entity vectors, are reused from cache. No hosted migrations
or production database URLs are accepted.

Each run directory gets `manifest.json`, `report.json`, and `hypotheses.json`,
plus separate `hypotheses.direct.json` / `hypotheses.hermes.json` exports suitable
for upstream evaluation without duplicate question IDs across modes.
Answers are checkpointed before judging. Restart the **same command** to resume;
compatible completed records are skipped and saved answers are graded without
regeneration. An interrupted answer request can use its exact cached response.
A changed dataset, source code, model, prompt, retrieval setting, split, or mode
requires a new run directory. Old question-ID-only reports cannot be imported.

Use `--replay` instead of `--live`, with a new run directory and the same profile,
to consume exact cached requests without credentials or network. Missing cache
entries fail rather than falling back to inference. Tool-probe results are bound
to the answer route; use `--probe-tools` during replay if cached probe responses
are available. Cached artifacts intentionally contain benchmark conversation text
and outputs; keep the artifact directory private.

## Reading results and current limits

Live provider checks on 29 October 2026 identified additional route settings:

- Nebius documents `max_completion_tokens` as bounding visible and reasoning
  output together. Setting `completion_limit_parameter` to that value maps the
  harness's `max_tokens` ceiling at the metered HTTP boundary, including Hermes
  requests. See the [provider API reference](https://api.tokenfactory.nebius.com/docs).
- Lightning's verified `reasoning_effort: "none"` avoids using the entire small
  completion allowance on reasoning. This optional route setting is fingerprinted;
  do not silently reuse earlier reasoning-enabled results.
- Embedding arrays need a larger, explicit response-byte allowance. A route can
  set `model_response_bytes` up to 1,048,576. Four 4,096-dimensional vectors per
  batch fit this bound in the tested provider response; the original 16-vector
  batch exceeded it. Interrupted/failed reservations remain in the same ledger.
- The answer policy allows new recommendations constrained by known user
  preferences; requiring the exact recommended meal to already exist in memory
  caused unnecessary abstention in the initial synthetic preference case.

These are harness/provider compatibility fixes, not evidence of general model
accuracy improvements. The four synthetic cases were used for development.

Reports expose planned/attempted/completed/graded counts, valid-grade accuracy,
all-attempted success rate, coverage, failures, invalid grades, budget skips, type
breakdowns, abstention results, packing omissions, paired outcomes and local
spend/reservations. Recall with no gold sessions is undefined, not 100%. Session
recall is still coarse: exact gold-turn coverage is not invented when labels are
absent. Provider/cache events link each stage to its raw-response fingerprint.

Use traces to distinguish a missing evidence session from a session lost during
packing. Session coverage alone cannot identify a reasoning error or prove that
all necessary answer text was supplied. No claim of improved model quality is
made from synthetic tests or a tiny pilot. Additional agent search, deterministic
calendar tools, full AgentService evaluation, Postgres/pgvector fidelity, broader
benchmarks, and a larger held-out study remain separate extensions justified by
the first controlled results. LoCoMo and Memory Arena proxy scripts are outside
this initial migration; their old live entry points do not inherit this ledger.
