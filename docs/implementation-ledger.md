# Remaining implementation ledger

20 October 2026, Asia/Calcutta. Starting commit `ba7a5f3`; clean working tree.
Local Python 3.11.0. Initial regression: 111 passed, 11 skipped. Docker daemon
unavailable; PostgreSQL, Redis and hosted migration state were not freshly
verified. Source migration head was 0017; prepared source head is now 0018.
The active hosted database was not migrated, and no code was published/pushed.

Final local validation: **122 passed, 11 skipped**, including the real pinned
Hermes engine/SDK and scripted learning/reuse checks. The separate synthetic live
NVIDIA smoke passed. Lint/format/whitespace checks passed. Reports:
[regression](hermes-validation-results.json), [live smoke](hermes-live-results.json).
The cached-archive setup command also passed. Hermes remains disabled by default.

The original separate 108-section controlling prompt is not present among the
repository source files. `reference-guide.txt` and the existing 108-section,
1,054-clause [requirements matrix](requirements-matrix.md) are available. Preserve
the matrix's unverified clauses; this ledger does not replace a manual clause
audit or claim that all remaining work is complete.

| Work | Current change/evidence | Remaining work and closure evidence | Status |
|---|---|---|---|
| Requirement audit | Current roadmap, architecture, reference and evidence entry points inspected; this ledger records current changes | Review each original clause against code and its actual acceptance evidence; obtain missing controlling source if needed | Partial |
| Hermes execution | Explicit opt-in backend, isolated pinned host, brokered model/tools; real-engine scripted recovery/learning/reuse and live NVIDIA smoke | Current-release runtime upgrade, Docker packaging, representative comparisons and live-model longitudinal learning/reuse acceptance | Partial |
| Execution authorization | Separate authenticated-agent allowlist; scope/lease/revision checks between operations; cancellation and erasure tests | Real multi-worker PostgreSQL and revocation/outage acceptance | Partial |
| Execution durability | Durable execution claim; journaled tool start/end; unknown-outcome recovery without replay | OS death, interrupted intent/result boundaries and broader side-effect reconciliation | Partial |
| Retention | Local profile isolation, disabled native memory/sessions/debug dumps; normal cleanup; non-retained Hermes explicitly rejected | Parent/OS-death cleanup and complete external-storage/provider retention policy | Partial |
| Full prompt budgets (M024) | Messages/tools/output/template-reserve checked; tests distinguish tokenizer and conservative modes | Provider-template calibration, longitudinal context usefulness, broader workloads | Partial |
| Graph retrieval (M008/M030/M031) | Per-hop incident-edge SQL replaces namespace-edge materialization; SQL-shape/reverse traversal tests; migration 0018 prepared | Deploy index after review, measure PostgreSQL plans and representative capacity; authorized-node enumeration remains | Partial |
| Lexical/ANN retrieval | Existing hybrid implementation preserved | Scalable lexical adapter, filtered ANN recall, pagination, representative corpus/ranking and cold/warm distributions | Partial |
| Discovery precision | Existing structured/model-assisted paths preserved | Labeled positive/negative domain corpus, false associations, no-finding behavior and counterevidence evaluation | Unverified breadth |
| Deterministic discovery | Existing recurrence/dependency/co-mention/time/sequence families retained | Quantitative anomaly/dependency miners and complete graph-motif families with evidence/counterexample gates | Partial |
| Finding lifecycle | Existing typed lifecycle/revision/invalidation retained | Reviewed semantic merge, supersession, retirement and full revalidation administration | Partial |
| Entity ambiguity | Existing exact-name linking retained | Same-name/pronoun resolution or explicit uncertainty; producer-aware identity evaluation and reviewed updates | Partial |
| Learning | Execution observations enter episodes with unknown outcome | Complex segmentation, conditional sequence abstraction, observed task outcomes and representative generalization | Partial |
| Serendipity | Existing bounded exploration retained | Remaining neighbor families, fairness and measured usefulness | Partial |
| Continuity | Existing authorization-partitioned, revision-checked snapshots retained | Longer-range identity/project coverage and longitudinal usefulness within budgets | Partial |
| Tenant settings | Existing typed override policy retained; new execution controls are administrator/environment settings | Complete supported-setting inventory and isolation/admin workflows; do not expose credential/tool authority as model-controlled overrides | Partial |
| Organizations | Existing same-user namespace/agent authorization retained | Organization membership lifecycle, role changes and revocation with explicit policy | Partial |
| Federation | No cross-user sharing enabled | Consent policy, sharing/revocation, provenance, export and deletion tests | External policy + implementation |
| Modalities | Artifact references remain | Real approved image/audio/document extraction, embeddings and retrieval evaluation | External provider + implementation |
| Service resilience | Existing leases/queue recovery preserved | Sustained API/worker restarts, database/Redis failures, quota/queue saturation and alerting | Unverified breadth |
| Encrypted backups | Existing backup/restore tooling unchanged | Encryption/key ownership, scheduled off-host destination, retention and isolated restore proof | External configuration + implementation |
| Secrets/alerts | Credentials remain in existing parent provider; not inherited by Hermes | Managed rotation and tested alert destinations/recipients | External configuration + implementation |
| Independent hosting | Local deployment target retained | Chosen persistent hosting, recovery and availability validation | External decision |
| Public ingress | No public deployment performed | Approved target, TLS/access/rate/storage hardening and verification | External decision |
| Product UI | Existing CLI/API preserved; CLI backend selection added | Polished UI remains separate optional scope | Optional |

Next engineering work should prioritize Docker/PostgreSQL/Redis availability and
Hermes execution/learning acceptance, then the requirement-level audit, scalable
retrieval and discovery/lifecycle quality. Enterprise and modality requirements
remain applicable. External configuration is not the only remaining work.
