# Completion execution checklist

The subsequent [implementation ledger](implementation-ledger.md) and
[Hermes acceptance notes](hermes-integration.md) describe local changes after
`ba7a5f3`. The historical baseline and test counts below are not fresh results.

Sources read: original 108-section master prompt, full MEM0 guide including five diagrams, earlier completion request and latest execution request. Existing Python stack, Supabase and NVIDIA providers remain in place. No public deployment or GitHub push is authorized by this request.

Baseline: clean main at a11c32c; 104 tests pass with isolated local PostgreSQL schemas and Redis database 15. Supabase application connection uses TLS without superuser/RLS bypass. Running worker logs show reflection completion, not only a heartbeat. Active model space remains Nemotron 3 Embed 1B / 2048 dimensions.

| Order | Work | Current acceptance |
|---|---|---|
| 1 | Dependency-scoped deletion and job cancellation | Passed scoped deletion, lease cancellation and unrelated-job preservation fixtures |
| 2 | General finding deduplication, revision and counterevidence | Passed stable-ID support/counterevidence and candidate expiry fixtures; semantic merging remains partial |
| 3 | Budgeted reusable context and persistent derived continuity | Passed tokenizer, source correction/deletion and cross-agent ACL fixtures; active tokenizer verified |
| 4 | Durable authenticated assistant turn and outcome loop | Passed worker, API, replay, interruption and real NVIDIA recall/outcome/procedure acceptance |
| 5 | Additional bounded deterministic discovery families | Structured recurrence/dependency/co-mention/time/sequence miners implemented; full motif/anomaly catalog remains partial |
| 6 | Experience/procedure and serendipity integration | Observed ordered procedures, recovery, model-assisted partitioning and three neighbor families implemented; representative quality unverified |
| 7 | Fair worker scheduling, progress and recovery | Bounded event batches, ten-minute queue aging, progress health, lease recovery and quota backoff fixtures passed |
| 8 | End-to-end, security and bounded live-provider acceptance | Real NVIDIA loop passed; hosted TLS/grants/forced RLS verified; hosted backup restored locally; sustained outages not tested |
| 9 | Documentation, contracts and requirement evidence | Current report, OpenAPI, startup and matrix supplement updated; full clause audit stays unverified |
| 10 | Account-dependent deployment and operational controls | Local target retained; external dependencies tracked explicitly |

The full requirement inventory remains in requirements-matrix.md. A checklist entry or test count is not full specification acceptance. Preserve unverified clauses until their behavior is demonstrated.

Current implementation and acceptance boundaries: [memory-loop-acceptance.md](memory-loop-acceptance.md). Hosted migration 0014 to 0017 preserved all 125 original canonical IDs. A later backup restored 126 records, including the newly generated continuity snapshot.
