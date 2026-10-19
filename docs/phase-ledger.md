# Implementation and acceptance ledger

All master capabilities remain part of the target. This records implemented initial behavior and the tests passed before advancement; interfaces and synthetic fixtures do not establish production model quality.

| Phase | Implemented behavior | Gate |
| --- | --- | --- |
| 1 Foundation | Schema, PostgreSQL/pgvector CRUD, audit, extraction, basic API/recall | 35 passed |
| 2 Hybrid | BM25, rewriting, candidate union, entity vectors, bounded context | 41 passed |
| 3 Temporal | Date normalization, mutation, supersession, disputes and history | 46 passed |
| 4 Episodes | Tool attempts/outcomes, segmentation and provenance | 49 passed |
| 5 Experience | Conditional strategies and structural analogy | 50 passed |
| 6 Graph | Evidence edges, bounded activation and causal guard | 52 passed |
| 7 Procedures | Repeated evidence and outcome feedback | 53 passed |
| 8 Transfer | Empty-session bootstrap, receiver ACL intersection and goals | 55 passed |
| 9 Reflection | Incremental mining, counterexamples and independent critic | 57 passed |
| 10 Serendipity | Weighted anchors, distant analogies and validation gates | 58 passed |
| 11 Dynamics | Decay, deep recall, pinning, clusters, triggers and loops | 61 passed |
| 12 Hardening | RLS, workers, Redis/outbox, scopes, export/deletion, policy and live verification | See verification.md |

The completion pass activates real Nomic embeddings and a persistent separately provisioned worker, connects Nemotron proposal/critic calls, adds bounded general discovery and future opportunities, improves episode identity/task signals, adds vector/worker indexes, query-vector caching and shared ingress limits, and verifies backup restoration. The latest regression gate is 92 tests with PostgreSQL/Redis on Windows and Linux Docker. See verification.md for measured live results and completion-status.md for the remaining target depth. No production certification or exhaustive clause-level acceptance is claimed.
