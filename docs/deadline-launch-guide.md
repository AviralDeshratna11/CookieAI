# Full LongMemEval S launch

The requested run is evaluation of existing NVIDIA models, not weight training.
The full-baseline strategy permits all 500 questions without another short pilot.
Offline verification does not establish live model quality or a completion time.

## Prepared inputs and scope

- Dataset: `.benchmark-artifacts/data/longmemeval_s_cleaned.json`, 500 questions.
- Official file SHA256: `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
- Profile: [benchmark.nebius.full-s.json](../config/benchmark.nebius.full-s.json).
- Answer: `nvidia/Nemotron-3_5-Lightning`; independent judge:
  `nvidia/nemotron-3-super-120b-a12b`; semantic embeddings:
  `Qwen/Qwen3-Embedding-8B`, 4096 dimensions, batches of four.
- Hermes uses the pinned real backend and parent broker, scoped memory tools and
  deterministic calendar tool. This comparison excludes full AgentService mode.
- Sources stay isolated per question; no gold labels enter answer generation.
  All 500 IDs are included, with previous development exposure recorded.
- Thirteen questions repeat original session IDs with distinct histories. Internal
  session keys preserve those variants; original IDs remain for session recall.
  Twelve empty turns remain in the original file but are not embedded. Original
  turn indices are preserved. This preprocessing version invalidates old indexes.

## Cost and time

Prices in the prepared profile were verified on 29 October 2026. The estimates
use full request ceilings and measured source/entity strings, not an assumed
accuracy improvement or guaranteed provider bill.

| Full S run | Embeddings | Answers | Judge | Conservative new-run quote |
| --- | ---: | ---: | ---: | ---: |
| Direct and Hermes, same 500 IDs | $4.0197 | $4.4237 | $10.2912 | $18.7346 |
| Hermes only, all 500 IDs | $4.0197 | $3.3178 | $5.1456 | $12.4831 |

Both plans propose a **$20 cumulative cap with $5 reserved** from the stated $25
balance. Previous spend/reservations of $0.00752852 remain included under that cap.
Neither plan is approved or launched by preparing these files. Choose one plan;
launching both would repeat work and require a new combined cost review.

Time is a material deadline risk. The conservative plan includes 394,138 vectors
and up to 104,719 embedding requests before answer/judge requests. At a hypothetical
one second per embedding request alone that is approximately 29 hours; actual
cache reuse, latency and counts can differ. No end-to-end completion time is
verified. Hermes-only reduces answer/judge work but retains the same indexing.
This implementation remains sequential. It does not claim to finish by tomorrow.
Increasing batch size or concurrency without verification is a different plan.

Rolling storage retains the current question's recoverable index and embedding
cache until answer stages finish, then releases generated scratch. It preserves
raw model responses, reports and the billing ledger. The planning allowance is
approximately 1.55 GB of scratch plus report growth; launch checks free space.
Completed instances cannot supply deleted scratch for a new experiment without
reindexing. Compatible partial work remains reusable during resume.

## Offline preparation and review

Run from the repository root in PowerShell. These commands make no requests:

```powershell
# Paired full comparison; no pilot required by this explicit strategy.
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline plan --data .benchmark-artifacts\data\longmemeval_s_cleaned.json --profile config\benchmark.nebius.full-s.json --mode compare --dataset-profile s_cleaned --split all --limit 500 --launch-strategy full_baseline --max-cost-usd 20 --max-calls 300000 --reserve-usd 5 --experiment-id deadline-compare-longmemeval-s --output .benchmark-artifacts\deadline-full-s-plan

# Or prepare Hermes only; choose this instead of launching both.
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline plan --data .benchmark-artifacts\data\longmemeval_s_cleaned.json --profile config\benchmark.nebius.full-s.json --mode hermes --dataset-profile s_cleaned --split all --limit 500 --launch-strategy full_baseline --max-cost-usd 20 --max-calls 300000 --reserve-usd 5 --experiment-id deadline-hermes-longmemeval-s --output .benchmark-artifacts\deadline-hermes-s-plan

$planDir = '.benchmark-artifacts\deadline-full-s-plan'
$planFile = Join-Path $planDir 'plan.json'
$approvalFile = Join-Path $planDir 'approval.json'
$runDir = '.benchmark-artifacts\deadline-full-s-run'
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline validate --plan $planFile
Get-Content (Join-Path $planDir 'cost-plan.json')
```

For Hermes only set `$planDir` to `.benchmark-artifacts\deadline-hermes-s-plan`
and `$runDir` to `.benchmark-artifacts\deadline-hermes-s-run`.
Inspect the entire selected ID list, routes, price date and prior ledger before
approving. Changing code/profile/data requires a new plan and approval. Never
replace the ledger or use another artifact root to reset spending.

## Credentials and discovery: network, no inference

Supply a current private credential in the process environment. Do not paste it
into source files or command history. One PowerShell option is:

```powershell
$credential = Get-Credential -UserName 'tokenfactory' -Message 'Enter the current Token Factory API key in the password field'
$env:NEBIUS_API_KEY = $credential.GetNetworkCredential().Password
.\.venv\Scripts\python.exe -m scripts.nebius_preflight
```

The last command lists account-visible NVIDIA models through `/models`; it does
not perform inference. Do not add `--inference`: that separate probe is billable
and outside these plans. Current account entitlement, remaining provider balance
and endpoint availability must still hold when launching. The models were live
tested in the earlier diagnostic; this review did not repeat hosted validation.

## Operator approval and paid launch

Execute this block only when you accept the selected frozen plan and $20
cumulative allocation. These first two commands record approval and migrate the
original ledger without spending tokens. Approval expires after 24 hours.

```powershell
$planSha = (Get-Content (Join-Path $planDir 'approval.template.json') -Raw | ConvertFrom-Json).plan_sha256
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline authorize-evaluation --plan $planFile --approval $approvalFile --confirm-plan-sha $planSha --confirm-cost-usd 20 --approval-reference 'Operator approves selected full S evaluation and cumulative USD 20 cap'
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline approve-policy --plan $planFile --approval $approvalFile

# BILLABLE: isolated indexing, model answers, Hermes and semantic grading.
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline execute --plan $planFile --approval $approvalFile --live --run-dir $runDir
```

The migration preserves previous charges and uncertain reservations. No approval
record or cap increase was applied during this architecture review. A fresh
approval path is required if an earlier approval file exists; never overwrite
approval history. All calls, including retries, share the original ledger.

## Resume and inspect

```powershell
# BILLABLE only for unfinished, compatible stages.
.\.venv\Scripts\python.exe -m scripts.experiment_pipeline resume --plan $planFile --approval $approvalFile --live --run-dir $runDir

# Offline report inspection.
$report = Get-Content (Join-Path $runDir 'report.json') -Raw | ConvertFrom-Json
$report | Select-Object planned, attempted, completed_answers, valid_grades, correct, accuracy_among_valid_grades, all_attempted_success_rate
Get-ChildItem -LiteralPath $runDir
```

Use the same plan/run directory. Saved answers resume into grading. Terminal
invalid outputs stay visible rather than silently regenerating until correct.
Authentication/payload errors, ingestion failures and network ambiguity stop
further work. Investigate before resuming. Stale owner/unknown request claims
require manual inspection; never clear them while another process is active or
assume a timed-out request was free. Renew an expired approval with a new file.

Keep the terminal and computer awake for the run. Reports include all-attempted
success, valid-grade accuracy, completion, invalid outputs and failures. A full
baseline can measure poor performance; it does not promise an improved score.
No fine-tuning upload, job submission, endpoint deployment or production route
change is part of these commands.
