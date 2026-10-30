# Live benchmark pilot - 29 October 2026

Connected the supplied Token Factory account and completed the initial capped
pilot. No further paid work is running. The $25 balance was not treated as a
spending target.

| Run | Direct | Hermes | Interpretation |
| --- | --- | --- | --- |
| Four synthetic development cases | 4/4 correct | 4/4 correct | Plumbing and prompt development only |
| Three official LongMemEval oracle questions | 1/3 correct | 0/3 correct | Hermes had 2 wrong answers and 1 invalid final output |

Five of six oracle attempts received valid grades; valid-grade accuracy is 20%,
all-attempted success is 16.7%. This tiny diagnostic does not estimate full-dataset
performance or demonstrate improvement. It uses only oracle evidence sessions,
not the full long-history distractor setting.

Answers used `nvidia/Nemotron-3_5-Lightning`; grading used the independently
configured `nvidia/nemotron-3-super-120b-a12b`; semantic retrieval used
`Qwen/Qwen3-Embedding-8B` with 4,096-dimensional vectors. Hermes ran through the
real pinned parent broker; these results exclude the full AgentService pipeline.

## Cost

The cumulative ledger contains **83 attempted HTTP calls** across model probes,
both synthetic runs, failed embedding attempts, and the oracle run:

- Settled estimated cost: **$0.00606986**.
- Uncertain failed requests retained: **$0.00133608**.
- Interrupted request still reserved: **$0.00012258**.
- Total spent or reserved: **$0.00752852**, less than one US cent.

These are local usage-based estimates and conservative reservations, not an
independent reading of the provider's balance or final invoice. Reservations
were retained instead of treating interrupted requests as free. The $1 and
100-call limits remain in place. No production provider or database was changed.

## Findings

1. The initial direct baseline exhausted its token cap on reasoning. The provider
   supports `max_completion_tokens` for bounding reasoning plus final output;
   verified `reasoning_effort: none` fixed this on the synthetic cases.
2. Sixteen 4,096-dimensional vectors exceeded the HTTP response-byte allowance.
   The pilot now uses four-vector batches and an explicit 1 MiB response bound.
3. On the jewelry multi-session question, only two of three gold sessions reached
   generation. Both paths then abstained incorrectly. Retrieval/context selection
   needs attention before buying a larger benchmark run.
4. On the gardening temporal question, both relevant dates reached generation.
   Direct predicted 16 days and Hermes 14; the reference is 6 days, with 7 inclusive
   accepted. Correct timestamp delivery alone does not solve date reasoning.
5. Hermes's real-data preference response contained an unmatched `</think>` marker
   despite a stop finish reason. It was rejected as an invalid final answer; the
   harness did not strip reasoning and pretend the response was clean.

The recommendation prompt was also clarified: new suggestions may use known
preferences as constraints without requiring the exact recommendation to have
appeared in history. That change was developed on synthetic cases before the
real-data pilot; those development scores are not held-out quality evidence.

## Artifacts and validation

- [Machine-readable live summary](benchmark-live-validation.json)
- [Corrected synthetic results](benchmark-live-synthetic-results-v2.json)
- [Initial synthetic failures](benchmark-live-synthetic-results.json)
- [Oracle results, evidence, and manifests](benchmark-live-oracle-results.json)
- [Harness usage](benchmark-harness.md)

The final focused regression run passed **47 tests**, with **2 existing
environment-gated tests skipped**. Both new real pinned-engine tests ran. Ruff
and whitespace checks passed. The account key is in the ignored `.env.nebius`
file, not reports or tracked source. Rotate the key that was pasted in chat.

Next work should be offline retrieval diagnosis and bounded date-tool support.
A larger paid run needs a new priced sample plan; the current results do not
justify spending the rest of the credits.
