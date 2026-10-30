# Evaluation and training pipeline

This implementation prepares full-dataset evaluation and a separate fine-tuning
lifecycle. It does not claim that the new harness fixes model quality, that a
training job has run, or that inference credits establish training entitlement.
All work in this implementation pass is offline except reading public provider
documentation. The earlier paid ledger remains intact.

The 30 October architecture review adds `--launch-strategy full_baseline` for an
operator who chooses complete evaluation without another short pilot. It skips
the pilot-quality gate only; frozen inputs, pricing, capability, cumulative budget
and approval checks remain. Manifests mark live quality as unvalidated. The
default `validated` strategy retains the held-out gate below. See the
[deadline launch guide](deadline-launch-guide.md).

## Architecture and implemented changes

Evaluation follows this path:

```text
validated dataset -> frozen plan + effective policy + cost quote
                 -> exclusive, resumable instance index
                 -> MemoryService candidates / ranking / selection traces
                 -> source-session/role-balanced evidence packing
                 -> direct answer | pinned Hermes | real AgentService route
                 -> strict native response classification
                 -> independent judge -> atomic reports + paired comparisons
```

`MemoryService` now accepts an optional explicit policy and optional search
observer. Normal application callers retain administrator/tenant/environment
policy behavior. Benchmark settings exclude environment/dotenv sources entirely,
including malformed ambient JSON. Each manifest records the effective policy.

The old 8,000-token retrieval allowance could discard a source before the
harness's 12,000-token evidence packer saw it. New selection traces identify
candidate membership, score/rank information, retrieval-budget exclusions, and
rank exclusions. Final packing records its own exclusions. A source can still
be missed; the implementation makes that loss observable rather than claiming
it cannot happen.

Source preprocessing is versioned. Chunks are at most 1,200 characters with exact
offsets, original role/text/date and parent-turn identity; they are smaller than
the earlier 12,000-character chunks. Packing cycles through session/role queues
without using question type or gold evidence. Original source text stays separate
from canonical indexing text. Stable source prefixes still prevent the application's
content deduplication from merging repeated statements across sessions; their
ranking effect remains an ablation to measure, not an eliminated risk.

The default **benchmark** retrieval allowance is now 24,000 conservative tokens;
the final evidence allowance remains independently bounded. Use a profile with
`retrieval_policy.max_memory_tokens: 8000` for a controlled old-budget ablation.
This changed allowance, chunking, and packing must not be reported as a pure
model improvement. Existing historical manifests cannot resume under this code.

## Hermes tools and application mode

Explicitly injected benchmark extensions expose:

- `benchmark_search`: at most two scoped searches.
- `benchmark_expand`: at most two source expansions, with radius at most two.
- `benchmark_date_interval`: at most four operations, using cited source IDs and
  ISO dates with elapsed/inclusive day semantics.

The parent validates strict argument models and executes the tools; the isolated
child receives only schemas and bounded results. Duplicate operations, unknown
source IDs and namespace crossing are rejected. The parent rechecks authorization,
erasure and source versions when reading and after model/tool activity. Total tool
calls are capped at eight and model calls at three. A tool-success flag does not
prove task success.

Calendar arithmetic handles leap days, year boundaries, reversed intervals and
explicit inclusive counting. Evidence resolution is deliberately narrower: ISO
dates in text and unambiguous `today`/`yesterday` references to a session date are
supported. “Last Friday,” month-only statements and ambiguous years are rejected
for this helper. Observation time alone is not treated as an event date. Broader
natural-language date resolution remains unsupported, not silently guessed.

`application` mode uses actual AgentService submission, context authorization and
transfer, pinned Hermes execution, observation/outcome persistence and raw turn
retention. `ContextPacket` now includes observation/event dates and source session
IDs, with the same full-context budget checks. All experiment instances remain
isolated. This mode does not run background discovery/learning workers; queued
work is not claimed as completed learning. It is a separate scope from the direct
versus backend comparison.

Production default tool sets are unchanged. Upstream Hermes source files and their
interface pin are unchanged. The parent/runner bridge supports the explicitly
injected benchmark schemas; no shell, arbitrary Python, database credentials or
provider keys are exposed to the child.

## Response handling

The `strict-native-v2` adapter distinguishes final answers, valid tool calls,
reasoning-only replies, refusals, length truncation, malformed envelopes, mixed
reasoning/final content and incomplete responses. Unmatched `</think>` remains
invalid. No generic tag stripping or unbounded repair is enabled.

The provider boundary retains `max_completion_tokens` mapping and fingerprinted
reasoning settings. It owns deadlines and token/cost reservations, including
Hermes requests. The real provider's response-byte limit is explicit. Clean native
final content is accepted; this is protocol validation, not a semantic guarantee
that every free-text sentence is a final answer rather than unwanted commentary.

## Offline evaluation commands

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline audit --output .benchmark-artifacts\audit
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline plan --data tests\fixtures\longmemeval_synthetic.json --mode retrieval-only --split all --output .benchmark-artifacts\offline-plan
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline validate --plan .benchmark-artifacts\offline-plan\plan.json
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline index --plan .benchmark-artifacts\offline-plan\plan.json
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline execute --plan .benchmark-artifacts\offline-plan\plan.json --run-dir .benchmark-artifacts\offline-run
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline resume --plan .benchmark-artifacts\offline-plan\plan.json --run-dir .benchmark-artifacts\offline-run
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline status --run-dir .benchmark-artifacts\offline-run
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline readiness
```

These commands do not read API keys or make inference calls. Plans are tied to
code/data/profile fingerprints; recreate a plan after code or configuration changes.
`--split all --limit 500` selects all 500 IDs, rather than silently selecting only
the development partition. Full results must still disclose prior development
exposure. Hash embeddings are plumbing fixtures, not semantic retrieval evidence.

Indexes live under the ignored artifact root, keyed by question/history,
preprocessing, projection implementation, embedding identity and effective policy.
Each accepted source is checkpointed. Compatible completed sources are reused;
embedding caches recover a crash between inference and source commit. Evaluation
answers are not ingested into these reusable corpus indexes. Application execution
uses its own disposable database.

Run/index owner files prevent concurrent mutation. A crash can leave an owner
file: inspect the recorded PID and run state before manually clearing a stale
claim. There is no automatic timeout that assumes another process or provider
request has finished. Retain pending/uncertain cost reservations during recovery.

## Full and paid evaluation

Prepare a frozen plan first; the following is planning only:

```powershell
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline plan --data data\longmemeval_s_cleaned.json --dataset-profile s_cleaned --profile config\benchmark.nebius.local.json --mode compare --split all --limit 500 --max-cost-usd 5 --max-calls 10000 --reserve-usd 20 --output .benchmark-artifacts\full-plan
```

The `$5` is an example proposed **cumulative** allocation including prior spend;
this command does not approve it. The cost quote uses actual source/entity strings,
deduplicated projection counts, batch size, query-rewrite/search bounds and full
request ceilings. Historical pilot token costs are separate scenarios, not an
expected-price guarantee. A conservative full quote may exceed the proposed cap;
execution then fails closed instead of assuming it will be cheap enough.

Before any new paid run, review the selected IDs, exposed development cases, model
routes, independent judge, semantic embeddings, current prices, cost quote and
protocol acceptance criteria. The default validated strategy requires a held-out
pilot before the full run. Offline correctness is not a successful live quality gate.
Full paid execution additionally requires `--validation-report <heldout-report.json>`
when preparing a `validated` strategy plan. The report must match the frozen corpus, profile,
code and modes, use unexposed held-out IDs, cover at least six questions, complete
at least 95% of answers and have at most 2% invalid final outputs. These are
protocol thresholds, not a promised accuracy target. Preparing a plan without
that report is allowed; launching a validated-strategy run without it is rejected.
An explicitly approved `full_baseline` strategy instead measures the complete
dataset with unvalidated live quality, matching the user's direct-full-run choice.

Planning creates `approval.template.json`. A human approval record must name the
action, exact plan fingerprint, approver, approval reference and UTC validity
window. Empty, expired, future-dated or mismatched records fail validation. This
is an auditable local operator control, not a cryptographic identity system.

Only after explicit approval, the operator can apply the reviewed allocation:

```powershell
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline approve-policy --plan .benchmark-artifacts\full-plan\plan.json --approval .benchmark-artifacts\full-plan\approval.json
```

This migration preserves original rows, reservations and revision history in the
same ledger. It refuses a transition during an in-flight model claim. Increasing
limits by reopening the file or selecting a new artifact root is not the workflow.
An instance still honors its own smaller cap after a parent cap is increased.

The explicitly billable operation is then:

```powershell
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline execute --plan .benchmark-artifacts\full-plan\plan.json --approval .benchmark-artifacts\full-plan\approval.json --live --run-dir .benchmark-artifacts\full-run
```

This is a documented future operator action; it has not been run in this pass.
Tool protocol probes must already be available for the exact answer route.
Use `--replay` instead of `--live`, with a new run directory, for exact cached
responses only. Cache misses fail; credentials and network are not used.

`grade` resumes only when saved records exist for every planned question/mode and
answers are already present; it cannot regenerate an absent answer silently.
`resume` can continue earlier pipeline stages. Reports preserve invalid-final and
invalid-grade counts, coverage, all-attempted success, per-type breakdowns, paired
disagreements and Wilson intervals. Tiny sample intervals do not establish a gain.

## Training data and supported job lifecycle

Training is separate from inference and memory ingestion:

```text
independent/consented examples -> lineage components + overlap checks
 -> reviewed clean targets -> grouped train/validation/test JSONL
 -> data card + hashes + token counts + capability/job plan
 -> explicit upload approval -> explicit submission approval
 -> queued/running/terminal status -> verified checkpoint -> paired evaluation
 -> explicit promotion review (no automatic deployment)
```

Offline preparation:

```powershell
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline training-data --output .benchmark-artifacts\training-data --benchmarks data\longmemeval_oracle.json
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline training-plan --data .benchmark-artifacts\training-data --output .benchmark-artifacts\training-data
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline training-validate --plan .benchmark-artifacts\training-data\training-plan.json --data .benchmark-artifacts\training-data --job .benchmark-artifacts\training-job.json
```

Omit `--benchmarks` only for a synthetic plumbing exercise. Pass **all** evaluation
variants that will be used for real training validation. Exact IDs, normalized
source hashes and 12-word phrase overlap are checked; linked source/group
components stay in one split. Exposed pilot IDs are explicitly forbidden.
Semantic paraphrase contamination is not automatically proven absent. All source
lineage sharing a revoked source is excluded. Consented examples with detected
email/phone data get a redacted review artifact and are excluded from training
until their targets are reviewed again. This is not a comprehensive PII detector.

The 24 independently authored examples exercise calendar/update/evidence/
preference/abstention/tool protocol mechanics. Their data card labels them smoke
data. The generator consumes no benchmark answers or private reasoning. The
adapter validates tool IDs and final targets; model-specific provider-schema
verification is still needed before upload.

Current Lightning capability is deliberately blocked. The public supported
[fine-tuning model list](https://docs.tokenfactory.nebius.com/post-training/models)
does not establish Lightning support or account entitlement. Training prices and
credit eligibility remain unverified. No alternate base model is silently chosen.

The HTTP adapter implements documented file upload, job creation, status/events,
cancellation and checkpoint-list endpoints. Its LoRA/context/hyperparameter mapping
uses the provider's [fine-tuning API](https://docs.tokenfactory.nebius.com/post-training/how-to-fine-tune).
Real mutation requires matching action approvals and verified capability, schema,
pricing, context limits and maximum liability. The job liability is reserved in
the same ledger before upload; each HTTP operation consumes the shared call cap.
Duplicate upload/submission identities are persisted. Ambiguous submission becomes
`UNKNOWN`, never an automatic resubmission. Cancellation acknowledgment remains
`CANCEL_REQUESTED`; funds are held until terminal status and billing reconciliation.

Future authorized operations use `training-upload`, `training-submit`,
`training-status`, `training-cancel` and `training-checkpoints`, each with
`--plan`, `--data`, `--job`, `--approval` and explicit `--live`. Upload requires
`training_upload` approval; the other job operations use `training_submit` approval.
These operations fail closed for the current NVIDIA capability snapshot.

Successful checkpoint binding requires immutable job/checkpoint identity and a
verified downloaded artifact SHA256. A typed comparison contract fixes corpus,
IDs, policy, answer prompt, response adapter, judge, base model and checkpoint.
`compare-checkpoint --plan <comparison.json> --base-report <base.json>
--trained-report <trained.json>` validates paired reports and writes reviewable
results. It rejects changed harness code/modes/retrieval/embedding settings.
Promotion planning includes the base rollback route and never changes production.

## Readiness and unresolved gates

Implemented and offline-tested mechanics do not establish full live readiness.
New held-out semantic retrieval, output validity, date resolution/tool use and
application behavior must be validated under an explicitly priced pilot. Broader
date language, Postgres/pgvector fidelity, background-learning workers, real
training uploads/jobs, provider billing reconciliation and deployment remain
unverified or unsupported as documented.

See [readiness validation](experiment-pipeline-validation.json) for checks actually
run, [recorded failure audit](experiment-failure-audit.json) for historical evidence,
and [original live diagnostic](benchmark-live-results.md) for the unchanged paid
baseline. No new model-quality gains should be inferred from these offline changes.
