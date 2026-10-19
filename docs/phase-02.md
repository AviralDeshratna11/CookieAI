# Phase 2 hybrid retrieval

Implements true BM25 with document-frequency and length normalization; conservative query rewriting and an optional model rewriter; independent dense, lexical and entity candidate generation; configurable weighted signal fusion; diversity selection; conservative token-budget enforcement; typed untrusted context packets; and transactional lexical/entity-vector projections. Entity names resolve exactly within a namespace; approximate embedding similarity cannot permanently merge ambiguous people or concepts.

Migration 0002 adds memory_lexical, entities, entity_aliases, memory_entities and entity_embeddings. The first migration freezes its table membership so later tables are not accidentally created twice. Entity vectors are independent of memory vectors. Keyword and entity context is now supplied to atomic extraction.

Example: `service.search(ctx, SearchRequest(query="What was the database choice for Alpha?"))`; call `memory.context.composer.compose(hits)` to get epistemically separated model data.

Acceptance requires lexical recovery outside the vector pool, inverse-fanout specificity, authorized projections, full projection cleanup, bounded context and both schema migrations on PostgreSQL. Local suite: 39 passed; real PostgreSQL verification is recorded in the current implementation report.

Limits: the initial corpus is scored exactly in memory after authorization. This is appropriate for a bounded deployment; ANN indexing, large-corpus pagination and batch embeddings require performance hardening. Local query rewriting does not resolve ambiguous pronouns. Stored aliases support exact names; uncertain identity links belong to the graph phase. A model-endpoint rewriter is implemented but not validated against a downloaded local model.
