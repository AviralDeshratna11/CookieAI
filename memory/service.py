"""Domain logic has no FastAPI dependency. All writes share one database transaction."""

import hashlib
import unicodedata
from uuid import UUID

from sqlalchemy import delete, insert, select

from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.config import Settings
from memory.schemas import (
    EpistemicType,
    ExtractorContext,
    Memory,
    MemoryCreate,
    MemoryType,
    SearchHit,
    utcnow,
)
from memory.security.auth import Conflict, NotFound
from models.providers import validate_vector


def canonicalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


class MemoryService:
    def __init__(self, engine, embedder, extractor, settings: Settings):
        self.engine, self.embedder, self.extractor, self.settings = (
            engine,
            embedder,
            extractor,
            settings,
        )
        from memory.retrieval.cache import QueryVectorCache
        from memory.retrieval.hybrid import LocalQueryRewriter

        self.query_cache = QueryVectorCache(settings.query_embedding_cache_seconds)

        if settings.query_rewriter_backend == "compatible":
            from models.providers import CompatibleQueryRewriter

            self.rewriter = CompatibleQueryRewriter(settings)
        elif settings.query_rewriter_backend == "local-rule":
            self.rewriter = LocalQueryRewriter()
        else:
            raise ValueError("unsupported query rewriter backend")

    def vector(self, text):
        return validate_vector(self.embedder.embed(text), self.embedder.dimensions)

    def policy(self, repo):
        from database import operations_tables as operations
        from memory.policy import load_policy

        tenant = repo.db.execute(
            select(operations.tenant_policies.c.payload).where(
                operations.tenant_policies.c.namespace_id == repo.ctx.namespace_id
            )
        ).scalar()
        return load_policy(tenant=tenant)

    def _create(self, repo, proposal):
        # Ensure even injected test/provider objects pass the same schema boundary.
        proposal = MemoryCreate.model_validate(proposal.model_dump())
        if proposal.allowed_project_ids:
            if not set(proposal.allowed_project_ids).issubset(
                set(repo.ctx.project_ids)
            ):
                raise ValueError("cannot assign unverified project restrictions")
        canonical = canonicalize(proposal.text)
        values = proposal.model_dump()
        from memory.entities.store import names

        values["entities"] = names(proposal)
        if (
            proposal.privacy_class in {"PRIVATE", "HIGHLY_PRIVATE"}
            and not proposal.allowed_agent_ids
        ):
            values["allowed_agent_ids"] = [repo.ctx.requesting_agent_id]
        for parent in proposal.provenance_ids:
            evidence = repo.get(parent)
            # A derived object can never be less restrictive than any of its evidence.
            if evidence.allowed_agent_ids and (
                not values["allowed_agent_ids"]
                or not set(values["allowed_agent_ids"]).issubset(
                    set(evidence.allowed_agent_ids)
                )
            ):
                raise ValueError("derived memory would broaden evidence authorization")
            if set(evidence.allowed_project_ids) != set(proposal.allowed_project_ids):
                raise ValueError(
                    "derived memory must preserve evidence project restrictions"
                )
            privacy = {"PUBLIC": 0, "NORMAL": 1, "PRIVATE": 2, "HIGHLY_PRIVATE": 3}
            if privacy[proposal.privacy_class] < privacy[evidence.privacy_class]:
                raise ValueError("derived memory would lower evidence privacy")
        memory = Memory(
            **values,
            canonical_text=canonical,
            content_hash=hashlib.sha256(canonical.encode()).hexdigest(),
            semantic_hash=hashlib.sha256(canonical.casefold().encode()).hexdigest(),
            namespace_id=repo.ctx.namespace_id,
            owner_id=repo.ctx.user_id,
            embedding_model=self.embedder.model_id,
            embedding_version=self.embedder.version,
            source_agent_id=repo.ctx.requesting_agent_id,
            source_session_id=repo.ctx.session_id,
        )
        duplicate = repo.duplicate(memory.content_hash, repo.acl_hash(memory))
        if duplicate:
            # A repeated request does not increase truth confidence or independent evidence.
            return duplicate
        from uuid import uuid4

        from database import source_tables

        if memory.source_type != "DERIVED":
            if memory.source_id is None:
                memory.source_id = uuid4()
            existing = (
                repo.db.execute(
                    select(source_tables.sources).where(
                        source_tables.sources.c.id == memory.source_id
                    )
                )
                .mappings()
                .first()
            )
            if existing and existing["namespace_id"] != repo.ctx.namespace_id:
                raise ValueError("source reference crosses namespace")
            if not existing:
                repo.db.execute(
                    insert(source_tables.sources).values(
                        id=memory.source_id,
                        namespace_id=repo.ctx.namespace_id,
                        session_id=repo.ctx.session_id,
                        created_at=utcnow(),
                        payload={
                            "kind": "EXPLICIT_MEMORY_INPUT",
                            "source_type": memory.source_type,
                            "text": proposal.text,
                            "artifacts": [
                                artifact.model_dump(mode="json")
                                for artifact in proposal.artifacts
                            ],
                        },
                    )
                )
        repo.save(memory, self.vector(canonical), "CREATED")
        from memory.entities.store import project

        project(repo, memory, self.embedder)
        from memory.graph.service import sync

        sync(repo, memory)
        for parent in proposal.provenance_ids:
            repo.db.execute(
                insert(t.provenance).values(
                    parent_id=parent,
                    child_id=memory.memory_id,
                    namespace_id=repo.ctx.namespace_id,
                    kind="DERIVED_FROM",
                )
            )
        if memory.source_id:
            repo.db.execute(
                insert(t.provenance).values(
                    parent_id=memory.source_id,
                    child_id=memory.memory_id,
                    namespace_id=repo.ctx.namespace_id,
                    kind="SOURCE",
                )
            )
        return memory

    def create(self, ctx, proposal):
        ctx = ctx.model_copy(update={"requested_scope": "write"})
        with self.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            repo.session()
            return self._accept(repo, proposal)

    def _accept(self, repo, proposal):
        from memory.mutation.engine import MutationKind, classify

        if all((proposal.subject, proposal.predicate, proposal.object)):
            for previous in repo.recent(limit=None):
                kind = classify(proposal, previous)
                if kind in {MutationKind.TEMPORAL_UPDATE, MutationKind.CONTRADICTION}:
                    return self._mutate(repo, proposal, kind, previous)
        return self._create(repo, proposal)

    def _invalidate_descendants(self, repo, parent_id):
        from memory.schemas import Status

        pending, visited = [parent_id], set()
        while pending:
            parent = pending.pop()
            children = repo.db.execute(
                select(t.provenance.c.child_id).where(
                    t.provenance.c.parent_id == parent,
                    t.provenance.c.kind == "DERIVED_FROM",
                )
            ).scalars()
            for child_id in children:
                if child_id in visited:
                    continue
                visited.add(child_id)
                child = repo.get(child_id)
                values = child.model_dump()
                values.update(
                    status=Status.DISPUTED,
                    revision=child.revision + 1,
                    updated_at=utcnow(),
                )
                child = Memory.model_validate(values)
                repo.save(child, self.vector(child.canonical_text), "DISPUTED")
                pending.append(child_id)

    def _mutate(self, repo, proposal, kind, previous):
        from memory.mutation.engine import MutationKind
        from memory.schemas import Status

        if kind == MutationKind.IRRELEVANT:
            return None
        if kind == MutationKind.DUPLICATE:
            if canonicalize(proposal.text) != previous.canonical_text:
                raise ValueError(
                    "duplicate classification requires exact canonical identity"
                )
            return previous
        if kind == MutationKind.REINFORCEMENT:
            if (
                canonicalize(proposal.text) != previous.canonical_text
                or proposal.epistemic_type != previous.epistemic_type
            ):
                raise ValueError("reinforcement cannot rewrite an explicit statement")
            repo.audit(previous, "REINFORCED")
            return previous
        if kind in {MutationKind.REFINEMENT, MutationKind.EXCEPTION, MutationKind.NEW}:
            return self._create(repo, proposal)
        if (
            previous.allowed_agent_ids != proposal.allowed_agent_ids
            and proposal.allowed_agent_ids
        ):
            raise ValueError("mutation cannot silently change authorization")
        values = proposal.model_dump()
        values.update(
            privacy_class=previous.privacy_class,
            allowed_agent_ids=previous.allowed_agent_ids,
            allowed_project_ids=previous.allowed_project_ids,
        )
        proposal = MemoryCreate.model_validate(values)
        new = self._create(repo, proposal)
        if new.memory_id == previous.memory_id:
            return previous
        old_values = previous.model_dump()
        old_values.update(revision=previous.revision + 1, updated_at=utcnow())
        new_values = new.model_dump()
        new_values.update(revision=new.revision + 1, updated_at=utcnow())
        if kind == MutationKind.CONTRADICTION:
            old_values.update(
                status=Status.DISPUTED,
                contradiction_count=previous.contradiction_count + 1,
            )
            new_values.update(status=Status.DISPUTED, contradiction_count=1)
        else:
            boundary = proposal.valid_from or proposal.observed_at
            if previous.valid_from and boundary <= previous.valid_from:
                raise ValueError("supersession boundary must follow old validity start")
            old_values.update(
                status=Status.SUPERSEDED,
                valid_until=boundary,
                superseded_by_memory_id=new.memory_id,
            )
            new_values.update(
                valid_from=boundary, supersedes_memory_id=previous.memory_id
            )
        old, new = Memory.model_validate(old_values), Memory.model_validate(new_values)
        repo.save(
            old,
            self.vector(old.canonical_text),
            "SUPERSEDED" if kind != MutationKind.CONTRADICTION else "DISPUTED",
        )
        repo.save(
            new,
            self.vector(new.canonical_text),
            "CORRECTED" if kind == MutationKind.CORRECTION else "UPDATED",
        )
        self._invalidate_descendants(repo, old.memory_id)
        return new

    def mutate(self, ctx, request):
        ctx = ctx.model_copy(update={"requested_scope": "write"})
        from memory.mutation.engine import MutationKind

        with self.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            repo.session()
            if request.operation == MutationKind.NEW:
                return self._accept(repo, request.candidate)
            if request.operation == MutationKind.IRRELEVANT:
                return None
            if request.target_id is None or request.expected_revision is None:
                raise ValueError("target and expected revision required")
            previous = repo.get(request.target_id)
            if previous.revision != request.expected_revision:
                raise Conflict("memory revision changed")
            return self._mutate(repo, request.candidate, request.operation, previous)

    def get(self, ctx, memory_id):
        ctx = ctx.model_copy(update={"requested_scope": "read"})
        with self.engine.begin() as connection:
            return SQLMemoryRepository(connection, ctx).get(memory_id)

    def patch(self, ctx, memory_id, patch):
        ctx = ctx.model_copy(update={"requested_scope": "write"})
        with self.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            memory = repo.get(memory_id)
            if memory.revision != patch.expected_revision:
                raise Conflict("memory revision changed")
            # Derived text must be recompiled from evidence, never edited into an unsupported claim.
            if memory.provenance_ids:
                raise Conflict("derived memory must be regenerated from evidence")
            descendants = connection.execute(
                select(t.provenance.c.child_id).where(
                    t.provenance.c.parent_id == memory_id,
                    t.provenance.c.kind == "DERIVED_FROM",
                )
            ).first()
            if descendants:
                raise Conflict(
                    "source has derived descendants; revalidation is required before editing"
                )
            values = memory.model_dump()
            values.update(
                patch.model_dump(exclude_unset=True, exclude={"expected_revision"})
            )
            if (
                values["privacy_class"] in {"PRIVATE", "HIGHLY_PRIVATE"}
                and not values["allowed_agent_ids"]
            ):
                values["allowed_agent_ids"] = [ctx.requesting_agent_id]
            if (
                values["allowed_agent_ids"]
                and ctx.requesting_agent_id not in values["allowed_agent_ids"]
            ):
                raise ValueError("writer must retain access to the memory")
            values["canonical_text"] = canonicalize(values["text"])
            values["content_hash"] = hashlib.sha256(
                values["canonical_text"].encode()
            ).hexdigest()
            values["semantic_hash"] = hashlib.sha256(
                values["canonical_text"].casefold().encode()
            ).hexdigest()
            values["embedding_model"] = self.embedder.model_id
            values["embedding_version"] = self.embedder.version
            values["revision"] += 1
            values["updated_at"] = utcnow()
            updated = Memory.model_validate(values)
            duplicate = repo.duplicate(updated.content_hash, repo.acl_hash(updated))
            if duplicate and duplicate.memory_id != memory_id:
                raise Conflict("update duplicates an existing memory")
            repo.save(updated, self.vector(updated.canonical_text), "UPDATED")
            from memory.entities.store import project, remove_orphans

            project(repo, updated, self.embedder)
            remove_orphans(connection, ctx.namespace_id)
            return updated

    def delete(self, ctx, memory_id):
        ctx = ctx.model_copy(update={"requested_scope": "delete"})
        with self.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            removed = repo.hard_delete(memory_id)
            from memory.entities.store import remove_orphans

            remove_orphans(connection, ctx.namespace_id)
            return removed

    def search(self, ctx, request):
        ctx = ctx.model_copy(update={"requested_scope": "read"})
        from memory.entities.store import scores as entity_scores
        from memory.retrieval.hybrid import bm25, diverse_select, terms

        with self.engine.begin() as connection:
            repo = SQLMemoryRepository(
                connection, ctx
            )  # authorize before invoking a model
            policy = self.policy(repo)
            rewrites = self.rewriter.rewrite(
                request.query,
                [
                    message.model_dump(mode="json")
                    for message in repo.rolling_messages()
                ],
            )
            if not 1 <= len(rewrites) <= 4 or any(
                not isinstance(q, str) or not q.strip() or len(q) > 4000
                for q in rewrites
            ):
                raise ValueError("invalid query rewrite proposal")
            pool = max(
                request.top_k * policy.overfetch_multiplier, policy.minimum_candidates
            )
            # All generators see the same authorized corpus; lexical/entity can add items outside ANN.
            corpus = repo.recent(
                limit=None,
                include_history=request.mode
                in {"DEEP", "AUTOBIOGRAPHICAL", "ASSOCIATIVE"},
                as_of=request.as_of,
            )
            from database import reflection_tables

            hidden_candidates = set(
                connection.execute(
                    select(reflection_tables.insights.c.id).where(
                        reflection_tables.insights.c.namespace_id == ctx.namespace_id,
                        reflection_tables.insights.c.payload["status"]
                        .as_string()
                        .in_(["CANDIDATE", "REJECTED", "INVALIDATED"]),
                    )
                ).scalars()
            )
            corpus = [
                memory for memory in corpus if memory.memory_id not in hidden_candidates
            ]
            permitted = [memory.memory_id for memory in corpus]
            if request.mode == "PROCEDURAL":
                corpus = [
                    memory for memory in corpus if memory.type.value == "PROCEDURAL"
                ]
                permitted = [memory.memory_id for memory in corpus]
            vectors, lexical_scores, entities = {}, {}, {}
            corpus_terms = [terms(memory.canonical_text) for memory in corpus]
            candidates = set()
            for query in rewrites:
                vector = self.query_cache.get(
                    ctx.namespace_id,
                    self.embedder.model_id,
                    self.embedder.version,
                    self.embedder.dimensions,
                    query,
                    lambda: validate_vector(
                        getattr(self.embedder, "embed_query", self.embedder.embed)(
                            query
                        ),
                        self.embedder.dimensions,
                    ),
                )
                for memory, value in repo.search(
                    vector,
                    self.embedder.model_id,
                    self.embedder.version,
                    pool,
                    include_history=request.mode
                    in {"DEEP", "AUTOBIOGRAPHICAL", "ASSOCIATIVE"},
                    as_of=request.as_of,
                ):
                    vectors[memory.memory_id] = max(
                        vectors.get(memory.memory_id, 0), value
                    )
                    candidates.add(memory.memory_id)
                keyword = bm25(query, corpus_terms)
                for index in sorted(range(len(corpus)), key=lambda i: -keyword[i])[
                    :pool
                ]:
                    if keyword[index] > 0:
                        memory_id = corpus[index].memory_id
                        lexical_scores[memory_id] = max(
                            lexical_scores.get(memory_id, 0), keyword[index]
                        )
                        candidates.add(memory_id)
                for memory_id, value in entity_scores(
                    repo, query, vector, permitted, self.embedder
                ).items():
                    entities[memory_id] = max(entities.get(memory_id, 0), value)
                    candidates.add(memory_id)
            from memory.graph.service import activation

            graph_scores = activation(
                repo,
                {key: score for key, score in vectors.items() if score >= 0.35},
                max_hops=policy.graph_max_hops,
                hop_decay=policy.graph_hop_decay,
                minimum=policy.graph_minimum_activation,
                permitted_memory_ids=permitted,
            )
            candidates.update(graph_scores)
            from memory.retrieval.context_signals import signals as contextual_signals

            extras = contextual_signals(repo, request, corpus)
            for generator in extras.values():
                candidates.update(generator)
            candidates.update(
                memory.memory_id
                for memory in sorted(corpus, key=lambda item: -item.importance)[:pool]
            )
            candidates.update(
                memory.memory_id
                for memory in sorted(
                    corpus, key=lambda item: item.created_at, reverse=True
                )[:pool]
            )
            scored = []
            now = utcnow()
            for memory in corpus:
                if memory.memory_id not in candidates:
                    continue
                signals = {
                    "semantic": vectors.get(memory.memory_id, 0),
                    "keyword": lexical_scores.get(memory.memory_id, 0),
                    "entity": entities.get(memory.memory_id, 0),
                    "graph": graph_scores.get(memory.memory_id, 0),
                    "associative": graph_scores.get(memory.memory_id, 0),
                    "importance": memory.importance,
                    "recency": 1
                    / (1 + max(0, (now - memory.created_at).total_seconds()) / 86400),
                }
                signals.update(
                    {
                        key: generator.get(memory.memory_id, 0)
                        for key, generator in extras.items()
                    }
                )
                weights = policy.scoring_weights
                score = sum(weights[key] * value for key, value in signals.items())
                scored.append((memory, score, signals))

            def conflict_key(memory):
                return (
                    (memory.subject, memory.predicate)
                    if memory.subject and memory.predicate
                    else (memory.memory_id,)
                )

            relevant_conflicts = {
                conflict_key(memory)
                for memory, score, _ in scored
                if memory.status.value == "DISPUTED"
                and score >= request.score_threshold
            }
            scored = [
                item
                for item in scored
                if item[1] >= request.score_threshold
                or (
                    item[0].status.value == "DISPUTED"
                    and conflict_key(item[0]) in relevant_conflicts
                )
            ]
            conflicts = [item for item in scored if item[0].status.value == "DISPUTED"]
            selected = diverse_select(
                scored,
                max(request.top_k, len(conflicts)),
                policy.max_memory_tokens,
                priority_conflicts=True,
            )
            from uuid import uuid4

            from database import operations_tables as operations

            connection.execute(
                insert(operations.retrieval_events).values(
                    id=uuid4(),
                    namespace_id=ctx.namespace_id,
                    agent_id=ctx.requesting_agent_id,
                    session_id=ctx.session_id,
                    created_at=utcnow(),
                    payload={
                        "mode": request.mode,
                        "candidate_count": len(candidates),
                        "selected_ids": [str(m.memory_id) for m, _, _ in selected],
                    },
                )
            )
            for memory, _, signals in selected:
                connection.execute(
                    insert(operations.access_events).values(
                        id=uuid4(),
                        namespace_id=ctx.namespace_id,
                        memory_id=memory.memory_id,
                        created_at=utcnow(),
                        payload={
                            "agent_id": str(ctx.requesting_agent_id),
                            "signals": signals,
                        },
                    )
                )
            return [
                SearchHit(memory=memory, relevance=score, why_retrieved=signals)
                for memory, score, signals in selected
            ]

    def export(self, ctx):
        ctx = ctx.model_copy(update={"requested_scope": "read"})
        with self.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            ids = db.execute(
                select(t.memories.c.id).where(
                    t.memories.c.namespace_id == ctx.namespace_id
                )
            ).scalars()
            result = []
            for item in ids:
                try:
                    result.append(repo.get(item).model_dump(mode="json"))
                except NotFound:
                    pass
            return {
                "user_id": str(ctx.user_id),
                "namespace_id": str(ctx.namespace_id),
                "memories": result,
            }

    def delete_namespace_memory(self, ctx):
        ctx = ctx.model_copy(update={"requested_scope": "delete"})
        with self.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            ids = list(
                db.execute(
                    select(t.memories.c.id).where(
                        t.memories.c.namespace_id == ctx.namespace_id
                    )
                ).scalars()
            )
            for item in ids:
                repo.get(item)  # Preflight all object ACLs before changing anything.
            removed = set()
            for item in ids:
                if item not in removed:
                    removed.update(repo.hard_delete(item))
            db.execute(
                delete(t.messages).where(
                    t.messages.c.session_id.in_(
                        select(t.sessions.c.id).where(
                            t.sessions.c.namespace_id == ctx.namespace_id
                        )
                    )
                )
            )
            db.execute(
                delete(t.ingestions).where(
                    t.ingestions.c.namespace_id == ctx.namespace_id
                )
            )
            from database import source_tables

            db.execute(
                delete(source_tables.sources).where(
                    source_tables.sources.c.namespace_id == ctx.namespace_id
                )
            )
            from memory.entities.store import remove_orphans

            remove_orphans(db, ctx.namespace_id)
            return {"namespace_id": str(ctx.namespace_id), "deleted": len(removed)}

    def provenance(self, ctx, memory_id):
        ctx = ctx.model_copy(update={"requested_scope": "read"})
        with self.engine.begin() as connection:
            return SQLMemoryRepository(connection, ctx).provenance(memory_id)

    def remember(self, ctx, request):
        ctx = ctx.model_copy(update={"requested_scope": "write"})
        with self.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            if not request.retain:
                return []  # Opt-out means no message/session/model persistence.
            policy = self.policy(repo)
            digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
            receipt_filter = (
                t.ingestions.c.namespace_id == ctx.namespace_id,
                t.ingestions.c.agent_id == ctx.requesting_agent_id,
                t.ingestions.c.idempotency_key == request.idempotency_key,
            )
            receipt = (
                connection.execute(select(t.ingestions).where(*receipt_filter))
                .mappings()
                .first()
            )
            if receipt:
                if receipt["request_hash"] != digest:
                    raise Conflict("idempotency key reused with different input")
                result = []
                for memory_id in receipt["memory_ids"]:
                    try:
                        result.append(repo.get(UUID(memory_id)))
                    except NotFound:
                        pass  # A retry must never resurrect deleted or newly inaccessible content.
                return result
            repo.session()
            if request.mode in {"raw", "procedural"}:
                proposals = [
                    MemoryCreate(
                        text=message.content,
                        type=MemoryType.OBSERVATION,
                        epistemic_type=EpistemicType.OBSERVED,
                        source_id=message.message_id,
                        observed_at=message.timestamp,
                    )
                    for message in request.messages
                ]
            else:
                text = "\n".join(message.content for message in request.messages)
                nearest = repo.search(
                    self.vector(text), self.embedder.model_id, self.embedder.version, 12
                )
                from memory.entities.store import scores as entity_scores
                from memory.retrieval.hybrid import bm25, terms

                corpus = repo.recent(limit=None)
                lexical = bm25(
                    text, [terms(memory.canonical_text) for memory in corpus]
                )
                lexical_memories = [
                    corpus[i]
                    for i in sorted(range(len(corpus)), key=lambda i: -lexical[i])[:12]
                    if lexical[i] > 0
                ]
                entity_matches = entity_scores(
                    repo,
                    text,
                    self.vector(text),
                    [m.memory_id for m in corpus],
                    self.embedder,
                )
                context = ExtractorContext(
                    agent_id=ctx.requesting_agent_id,
                    project_ids=ctx.project_ids,
                    messages=request.messages,
                    recent_memories=repo.recent(),
                    semantic_memories=[memory for memory, _ in nearest],
                    keyword_memories=lexical_memories,
                    entity_memories=[
                        memory
                        for memory in corpus
                        if memory.memory_id in entity_matches
                    ][:12],
                    recent_messages=repo.rolling_messages(),
                    conversation_date=request.messages[-1].timestamp,
                    privacy_policy={
                        "namespace_id": str(ctx.namespace_id),
                        "scope": ctx.requested_scope,
                    },
                    source_metadata={
                        "session_id": str(ctx.session_id),
                        "agent_id": str(ctx.requesting_agent_id),
                    },
                )
                from memory.schemas import Extraction

                extraction = Extraction.model_validate(
                    self.extractor.extract(context).model_dump()
                )
                source_map = {
                    message.message_id: message for message in request.messages
                }
                proposals = []
                for candidate in extraction.memories[: policy.max_memories_per_turn]:
                    source = source_map.get(candidate.source_message_id)
                    if not source or candidate.source_span not in source.content:
                        raise ValueError(
                            "extractor proposed unsupported source attribution"
                        )
                    if candidate.epistemic_type == EpistemicType.VERIFIED:
                        raise ValueError(
                            "extractor cannot self-certify a verified fact"
                        )
                    if candidate.allowed_agent_ids or candidate.allowed_project_ids:
                        raise ValueError("extractor cannot set authorization")
                    if candidate.memory_worthy and (
                        request.remember_explicitly
                        or candidate.memory_value() >= policy.extraction_threshold
                    ):
                        fields = {
                            key: getattr(candidate, key)
                            for key in MemoryCreate.model_fields
                        }
                        fields.update(
                            source_id=source.message_id, observed_at=source.timestamp
                        )
                        proposals.append(MemoryCreate(**fields))
            from database import source_tables

            for message in request.messages:
                if connection.execute(
                    select(source_tables.sources.c.id).where(
                        source_tables.sources.c.id == message.message_id
                    )
                ).first():
                    raise Conflict(
                        "source message identity already belongs to another interaction"
                    )
                connection.execute(
                    insert(source_tables.sources).values(
                        id=message.message_id,
                        namespace_id=ctx.namespace_id,
                        session_id=ctx.session_id,
                        created_at=utcnow(),
                        payload={
                            "kind": "RAW_MESSAGE",
                            **message.model_dump(mode="json"),
                        },
                    )
                )
            memories = [self._accept(repo, proposal) for proposal in proposals]
            if request.mode == "procedural":
                trace = self._create(
                    repo,
                    MemoryCreate(
                        text="Historical procedure trace: "
                        + " | ".join(message.content for message in request.messages)[
                            :15000
                        ]
                        + ". This trace is not a validated reusable strategy.",
                        type="PROCEDURAL",
                        epistemic_type="INFERRED",
                        source_type="DERIVED",
                        provenance_ids=[memory.memory_id for memory in memories],
                    ),
                )
                memories = [trace]
            repo.append_messages(request.messages, policy.rolling_messages)
            connection.execute(
                insert(t.ingestions).values(
                    namespace_id=ctx.namespace_id,
                    agent_id=ctx.requesting_agent_id,
                    idempotency_key=request.idempotency_key,
                    request_hash=digest,
                    memory_ids=[str(memory.memory_id) for memory in memories],
                )
            )
            return memories
