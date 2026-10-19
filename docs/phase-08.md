# Phase 8 context continuity

Migration 0007 adds goals and dependencies. Context bootstrap reconstructs identity, profile, goals, retrieved epistemic categories, entities, episodes and structurally relevant experiences/procedures from an empty session. The whole JSON package receives a conservative byte-based token bound. Transfer checks recipient grants before recall and intersects sender/receiver object visibility. No historical transcripts are copied. Goals support status/progress updates with revision checks.

Acceptance: new-session Alpha recall; B with read grant receives Alpha; private data is withheld; C without a grant fails; goals survive and appear in bootstrap; package remains bounded. Examples: POST `/v1/context/build` or `/v1/context/transfer` with query, optional structural fingerprint and recipient; POST/PATCH `/v1/goals` for explicit goal state.

Limits: the current identity model supports multiple agents for one user within namespace boundaries. Cross-user organization federation and managed tenant provisioning require explicit administrative policy. Autobiographical context is regenerated from canonical evidence at read time; asynchronous persistent summaries will remain evidence-dependent if added.
