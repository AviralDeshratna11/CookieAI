# Phase 6 graph and association

Migration 0005 adds typed graph nodes, evidence-bearing edges and evidence junctions. New memories project MENTIONS and DERIVED_FROM relationships transactionally. Explicit relations require authorized endpoints and evidence. Statistical/LLM associations cannot become CAUSES. Bounded cycle-safe spreading activation uses three hops, 0.55 decay, 0.10 minimum and a 500-node ceiling, and contributes to hybrid recall. Deletion removes endpoint and evidence-dependent edges.

Example: `GraphService(memory).connect(ctx, EdgeProposal(...))`; `recall(ctx,{memory_id:1})` returns association scores. Acceptance verifies hop attenuation, bounded cyclic traversal, evidence cleanup and causal-category protection.

Limits: the initial PostgreSQL graph uses exact traversal over namespace edges; partitioning and adjacency indexes are performance hardening work. Entity identity remains conservative; POSSIBLY_SAME_AS is an uncertain relation, never an automatic merge.
