# Memory system flows

The complete system diagram is in `architecture.md`. These diagrams define the target architecture; the phase ledger distinguishes implemented behavior.

## Ingestion

```mermaid
flowchart TD
  Turn[Completed turn] --> Auth[Authorize namespace and scope]
  Auth --> Context[Profile recent memories rolling ten messages dates]
  Context --> Modes{Ingestion mode}
  Modes --> Raw[Raw observation]
  Modes --> Extract[Atomic extraction proposals]
  Modes --> Procedure[Procedural evidence pipeline]
  Extract --> Resolve[Entity and temporal resolution]
  Resolve --> Mutation[Existing memory search and mutation classification]
  Raw --> Validate[Schema source ACL and quality gates]
  Mutation --> Validate
  Procedure --> Validate
  Validate --> Tx[Atomic persist vectors provenance audit and outbox]
  Tx --> Episode[Episode and graph jobs]
```

## Retrieval

```mermaid
flowchart TD
  Query[Query] --> Auth[Authorize first]
  Auth --> Rewrite[Up to four query rewrites]
  Rewrite --> Candidates[Vector BM25 entity graph time episode procedure goal candidates]
  Candidates --> Union[Union and overfetch]
  Union --> Normalize[Normalize separate relevance signals]
  Normalize --> Rank[Weighted reranking]
  Rank --> Select[Diversity contradictions and token budget]
  Select --> Context[Epistemically labeled context data]
```

## Cross-session transfer

```mermaid
flowchart LR
  Old[Session A] --> Ingest[Durable ingestion]
  Ingest --> Store[Canonical memory]
  New[Empty session B and new message] --> Bootstrap[Identity projects goals and recall]
  Store --> Bootstrap
  Bootstrap --> Package[Bounded provenance-bearing context package]
  Package --> Agent[New agent context]
```

## Cross-agent transfer

```mermaid
flowchart TD
  A[Agent A] --> Service[Memory service]
  B[Agent B] --> Auth[Credential and namespace grants]
  C[Unauthorized Agent C] --> Auth
  Auth --> Check{Permitted purpose and object ACL}
  Check -->|Allow| Service
  Check -->|Deny| Denied[No retrieval or model invocation]
  Service --> Package[Receiver-authorized context]
```

## Reflection

```mermaid
flowchart LR
  Cursor[Changed-since cursor] --> Evidence[Authorized independent experiences]
  Evidence --> Proposal[Pattern proposal]
  Proposal --> Counter[Counterexample search]
  Counter --> Critic[Independent critic]
  Critic --> Rules[Evidence privacy provenance validation]
  Rules --> Decision{Supported}
  Decision -->|Yes| Insight[Qualified derived insight]
  Decision -->|No| Reject[Reject or dispute]
```

## Serendipity

```mermaid
flowchart TD
  Sample[Weighted anchor selection] --> Neighbors[Semantic graph entity structural distant clusters]
  Neighbors --> Compare[Compare structure and differences]
  Compare --> None[Return NONE frequently]
  Compare --> Candidate[Evidence-bearing candidate]
  Candidate --> Support[Independent support and counterexamples]
  Support --> Critic[Separate critic and deterministic gates]
  Critic --> Persist[Persist candidate or validated relationship]
```

## Provenance

```mermaid
flowchart LR
  Source[Source message or artifact] --> Memory[Atomic memory]
  Memory --> Episode[Episode]
  Episode --> Experience[Experience]
  Experience --> Insight[Insight]
  Insight --> Procedure[Procedure]
  Experience --> Procedure
  Source --> Explain[Source attribution]
  Procedure --> Explain
```

## Deletion cascade

```mermaid
flowchart TD
  Delete[Authorized delete] --> Hide[Remove retrieval eligibility]
  Hide --> Descendants[Traverse provenance descendants]
  Descendants --> Derived[Remove or safely regenerate derived text]
  Derived --> Projections[Delete vectors graph entity references versions sources]
  Projections --> Cache[Invalidate working context and caches]
  Cache --> Audit[Content-free tombstone and deletion audit]
  Audit --> Event[Idempotent external deletion events]
```

## Experience compilation

```mermaid
flowchart LR
  Episodes[Real episodes] --> Fingerprint[Goal tools error environment stage outcome]
  Fingerprint --> Group[Structural similarity groups]
  Group --> Experience[Actions failures successes applicability exceptions]
  Experience --> Evidence[Provenance and independent evidence checks]
  Evidence --> Procedure[Candidate procedure after repeated examples]
  Evidence --> Recall[Analogous experience retrieval]
  Recall --> Outcome[Action and observed outcome]
  Outcome --> Episodes
```
