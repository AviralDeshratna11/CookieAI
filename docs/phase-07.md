# Phase 7 procedures

Migration 0006 stores conditional procedures and experience evidence. Compilation requires at least three distinct episodes or an attributed USER_STATED confirmation targeting the source experience. It preserves successful steps, tools, preconditions, failure modes and recovery strategies. Outcome feedback is evidence-backed, idempotent by evidence ID, audited and versioned; failures reduce confidence and every new outcome becomes a provenance dependency.

REST supports compile, get, search and feedback. Acceptance rejects a one-event learned rule, accepts three observed episodes and verifies subsequent failure lowers confidence. No procedure executes tools or external actions. Example: POST `/v1/procedures/compile` with experience_ids; search with the same structural query contract as experiences.

Limits: the compiler produces conditional historical strategies, not a causal guarantee. Trusted producers are responsible for accurate user attribution on explicit confirmations. Procedure sequence induction currently preserves the observed successful action order.
