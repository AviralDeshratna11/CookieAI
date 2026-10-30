# Architecture launch review, 30 October 2026

Scope: full benchmark evaluation using existing NVIDIA models. The operator can
choose a complete baseline without another pilot. No paid evaluation was run
during this review, and no weight-training job is involved.

## Findings and changes

| Finding | Implemented resolution | Evidence |
| --- | --- | --- |
| The original full-run gate required another held-out pilot | Explicit, fingerprinted `full_baseline` strategy; approval and budget gates remain | `EvaluationPlan`, `validate_protocol_gate`, harness manifest |
| Only tiny fixtures/oracle inputs had been validated | Downloaded the official cleaned S file, verified SHA256, validated all 500 IDs | Frozen full plans and `architecture-launch-review.json` |
| Repeated original session IDs rejected valid official inputs | Distinct history/date variants receive stable internal session keys; original IDs remain for scoring | `source_rows`, ingestion, neighbor expansion and broker expansion |
| Empty official source turns blocked all 500 questions | Validate text type, preserve raw data and original turn indices, explicitly omit empty projections | Twelve empty turns recorded in the manifest |
| Persistent indexes/caches risked filling local disk | Fingerprinted rolling storage with bounded, ownership-checked scratch release and free-space check | `_experiment_store.release_scratch`, harness and controller |
| Resume charged its admission estimate as if all stages were unfinished | Price unfinished answer/index/judge stages; preserve old reservations; terminal invalid records remain terminal | `remaining_cost_bound` and regression tests |
| There was no convenient concrete approval command | Exact plan SHA/cumulative-cap confirmation, non-overwriting 24-hour approval file; migration is still separate | `authorize-evaluation` tests |
| Calendar arithmetic and response protocol previously failed | Existing scoped deterministic date tool and strict response adapter retained and tested through pinned Hermes | Existing date, ACL, protocol and real-runtime scripted tests |

The earlier jewelry trace proves one required session did not reach generation;
it cannot distinguish the exact upstream loss stage. New selection/packing traces
provide that distinction on future runs. The gardening failure had the dates but
incorrect arithmetic; the deterministic helper fixes mechanics when correctly
selected dates are supplied. The unmatched reasoning delimiter remains invalid,
rather than being stripped to manufacture a graded final answer. No accuracy
improvement is established by this review.

Additional offline hardening covers training context validation before any upload,
submission state checks and equal output/context ceilings for checkpoint
comparison. Those paths are separate from the requested benchmark launch.

## Frozen launch artifacts

Final focused verification: **88 passed, zero skipped** in 163.96 seconds with
the pinned runtime selected. Coverage includes the real Hermes engine on scripted
transports, AgentService, broker restrictions, response formats, budget/resume,
policy isolation and full selection. Ruff checks passed. Both 500-ID frozen plans
validated with zero network calls. This is offline verification, not a live score.

- Paired plan: `.benchmark-artifacts/deadline-full-s-plan/plan.json`.
- Hermes-only alternative: `.benchmark-artifacts/deadline-hermes-s-plan/plan.json`.
- Each directory contains the entire selected ID list, a cost plan and an empty
  approval template. Neither contains a completed approval record.
- [Versioned model profile](../config/benchmark.nebius.full-s.json).
- [Machine-readable review, costs and readiness](architecture-launch-review.json).
- [Exact PowerShell launch and recovery guide](deadline-launch-guide.md).
- Historical failure audit replay:
  `.benchmark-artifacts/architecture-review/failure-audit.json`.

Both plans contain all 500 S IDs. The paired run plans 1,000 question/mode outcomes;
Hermes-only plans 500. Earlier development exposure is disclosed. They share a
proposed cumulative $20 allocation with $5 reserved, including the retained
$0.00752852 ledger total. The actual ledger remains at its earlier $1/100-call
policy until the operator explicitly approves and applies a migration.

Offline launch plumbing and full-input validation are ready. Current credentials,
account entitlement, provider billing and live reliability after the changes are
external prerequisites. The sequential embedding volume is a serious deadline
constraint; neither an overnight completion nor a higher score is verified.

The public dataset download was the only new network activity needed for these
artifacts. New inference spend: $0. No upload, training, deployment, production
setting change or automatic full run was performed.
