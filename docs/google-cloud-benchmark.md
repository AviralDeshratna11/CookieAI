# Google Cloud benchmark deployment

This runs the full 500-question direct/Hermes evaluation. NVIDIA models remain
hosted by Token Factory; the CPU VM runs ingestion, retrieval and the Hermes
parent/child processes. It does not host or fine-tune model weights.

## Resource and cost limits

- Project: `shared-gpu-avd-261030`; zone: `us-central1-a`.
- Current VM: `memory-benchmark-261030-r2`, `e2-standard-4`, four vCPUs and 16 GB RAM.
  The original `memory-benchmark-261030` was backed up and deleted after a
  pre-inference validation failure. Its costs remain in the allocation history.
- One 50-GB standard boot disk; no GPU, no extra VMs or autoscaling.
- Provider-enforced maximum runtime: 72 hours, termination action **DELETE**.
- $25 local cloud allocation reserved per lease under the user's total $250 ceiling;
  $50 conservatively reserved across the deleted first lease and current lease.
  Published VM-only rate: $0.13402284/hour, about $9.65 over 72 hours. Disk,
  external IP and network usage are additional; the allocation includes allowance.
- Token Factory keeps its independent $20 cumulative cap and previous charges.
  Cloud credits cannot pay that provider's bill.

The $250 account/project-wide hard cap is **not established** by this setup.
Google billing budgets and available spend caps do not stop ongoing fixed compute
or disk usage. The VM's scheduled deletion bounds this deployment's resource
lifetime. The local allocation record cannot control resources created outside
this workflow; do not use it as an authoritative billing guarantee.

Sources: [VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose?hl=en),
[runtime limits](https://docs.cloud.google.com/compute/docs/instances/limit-vm-runtime),
[billing spend-cap limitations](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps).
Prices checked 30 October 2026. No commitment or reserved capacity is purchased.

## Transfer and setup

The archive excludes environment files and credentials. It includes the official
S dataset, source, dependency pins, relevant fixtures, the original billing ledger
snapshot and already-paid first-question embedding responses. The stopped Windows
run and reports remain on the PC. Only the cloud copy may make further paid calls
after transfer; never resume both copies against independently copied ledgers.

On the VM, extract under `~/memory-benchmark` and run:

```bash
bash scripts/cloud/bootstrap_benchmark.sh
```

This installs the pinned dependencies and real Hermes source, runs offline tests,
and prepares a new Linux-path plan. It does not run inference. Linux paths and
four ingestion workers are recorded in the new profile; the old Windows plan is
retained as historical evidence rather than silently relabelled as compatible.

Embedding batches remain four vectors. Concurrency is four **bounded waves** of
embedding requests only, not four independent benchmarks. Every call uses the
same ledger. A failed wave drains already-submitted calls before stopping; it
does not queue the entire dataset or automatically retry failures. Retrieval,
answer generation and grading remain sequential. No deadline speedup is promised
before actual VM throughput is measured.

Atomic checkpoint writes retry transient local Windows rename denial separately
from inference. This prevents a monitor/read collision from causing a paid model
call to be repeated. The original PermissionError's exact stack was unavailable;
the sharing violation is a plausible diagnosis, not a proven filesystem audit.

## Run and observe

The cloud plan must receive a matching approval and policy migration, preserving
the old ledger. A private `NEBIUS_API_KEY` environment variable is required. Do not
put it in metadata, startup-script text, command arguments, documentation or logs.
The runner is:

```bash
.venv/bin/python -u -m scripts.benchmark_cloud_runner run
```

Run it under a system service so disconnecting SSH does not stop the job. The
monitor emits one credential-free JSON status every 20 seconds and writes:

```text
.benchmark-artifacts/cloud-full-s-run/live-status.json
.benchmark-artifacts/cloud-full-s-run/report.json
```

The local watcher pulls a snapshot every minute to
`.benchmark-artifacts/cloud-live/r2-v2/LIVE_STATUS.md` and `live-status.json`.
It verifies a downloaded SHA256 result/ledger/cache archive before deleting the
owned VM and disk. Failed terminal outcomes have a five-minute diagnostic window;
successful completion cleans up immediately after backup. That local cleanup
requires the PC to remain awake and connected. The independent cloud-side
72-hour deletion deadline still applies if the PC disconnects. No results should
be assumed backed up until `verified-backup.json` exists for the current lease.

The initial r2 full-run attempt stopped after one direct grade. Hermes rebuilt a
temporary corpus and made 368 individual embedding requests before timing out.
The corrected backend now reopens the same authorized per-question index used by
retrieval, rather than rebuilding it. It retains namespace/source checks and the
real pinned engine. Application mode keeps its separate disposable state, with
batched prewarming. The corrected run uses `cloud-full-s-plan-v2` and
`cloud-full-s-run-v2`; the prior attempt is retained unchanged. A regression test
asserts no reingestion occurs when Hermes reuses the completed index.

From Windows PowerShell, use `gcloud.cmd` because the `.ps1` shim may be blocked by
the local execution policy. No policy change is needed:

```powershell
gcloud.cmd compute ssh memory-benchmark-261030-r2 --project=shared-gpu-avd-261030 --zone=us-central1-a --command="sudo journalctl -u memory-benchmark -f -n 5"
```

No public dashboard port is opened. The notebook/PC can pull status over SSH;
the background service continues without the PC. The VM will be deleted at its
runtime limit, **including its auto-delete boot disk**. Download reports and the
final ledger before that limit. Stop conditions and failures remain visible;
there is no automatic job relaunch or automatic extension beyond the lease.

After downloading results, delete the owned VM promptly rather than leaving it
running until the 72-hour limit. Deleting the VM or its auto-delete disk erases
their contents, so verify the local result copy first. Further test deployments
must preserve the cumulative cloud allocation history and the authoritative
Token Factory ledger; do not reset either by starting a new artifact directory.
