# Phase 9 reflection

Migration 0008 adds indexed tool/configuration event features, insights, support/counterexample links and persisted processing cursors. Reflection reads changed features in bounded batches, searches all authorized matching evidence, proposes a conditional association and invokes a separate conservative critic. Weak evidence stays candidate; counterevidence can dispute an earlier result. Sensitive categories are rejected. Insight updates preserve epistemic type, provenance and audit history. GET `/v1/insights` and POST `/v1/reflection/run` expose the service; contextual recall labels derived correlations.

Acceptance seeds 100 episodes with a hidden ToolX/configurationY failure association, checks support and counterexamples, rejects two-sample patterns, and revises four supporting episodes after seven counterexamples. Repeated runs without changes do no new work. No causal claim or invented event is generated.

Limits: deterministic mining currently covers tool/configuration outcome associations. Additional event-sequence and graph-motif miners can implement the same evidence/critic boundary. Sensitive filtering uses an explicit schema/category denylist; production policy should be domain-reviewed. Counterexample absence never proves causality.
