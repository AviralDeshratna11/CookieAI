# Phase 5 experiences

Migration 0004 adds experience payloads and source-episode links. The compiler groups explicitly selected structurally compatible episodes, preserves unsuccessful and successful actions, outcomes, exceptions, applicability and all provenance. Fingerprints contain goal type, domain, tools, error category, environment, workflow stage, entities and outcome. Structural search is vocabulary-independent when these observed dimensions are supplied; missing dimensions reduce similarity rather than inventing context.

Single-event experiences remain low confidence. Compile via POST `/v1/experiences/compile`; query via POST `/v1/experiences/search` with a context_signature. Acceptance includes a 120-day-old TLS incident recalled in a new session using different words and matching structure, preserving the failed attempt and successful renewal, then removing the experience when evidence is deleted.

Limits: structural dimensions must be explicitly observed/extracted; the compiler does not assume a language embedding alone proves structural identity. Continuous incremental compilation will be wired through the worker phase.
