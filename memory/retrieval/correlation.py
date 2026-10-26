"""Cross-session memory correlation for the chat portal.

The existing `/v1/memory/search` path already ranks candidates across the
whole namespace: a session token scopes *who can write/own a turn*, not what
search can see. What was missing was a view that groups those cross-session
hits by their originating conversation and explains why they matched, so the
caller never has to already know which session token holds the relevant
history.

The grouping and "why correlated" explanation below are a deterministic
heuristic (shared terms and entities) — no reasoning-model call is made. It
is a drop-in seam: once a live reflection model is configured
(MEMORY_REFLECTION_MODEL, e.g. a Nemotron model through Nebius), `_explain`
can be replaced with a model-assisted summary without changing callers.
"""

from collections import defaultdict

from memory.retrieval.hybrid import terms
from memory.schemas import Field, SearchRequest, StrictModel
from memory.security.auth import require_scope


class CorrelateRequest(StrictModel):
    query: str = Field(min_length=1, max_length=4000)


def _explain(query_terms, session_hits):
    shared = defaultdict(int)
    for hit in session_hits:
        for term in set(terms(hit.memory.canonical_text)) & query_terms:
            shared[term] += 1
    return sorted(shared, key=shared.get, reverse=True)[:6]


def build_correlation(hits, query, current_session_id=None, max_sessions=8):
    query_terms = set(terms(query))
    clusters = defaultdict(list)
    for hit in hits:
        clusters[hit.memory.source_session_id].append(hit)
    ranked_sessions = sorted(
        clusters.items(),
        key=lambda item: max(hit.relevance for hit in item[1]),
        reverse=True,
    )
    sessions = []
    for session_id, session_hits in ranked_sessions[:max_sessions]:
        session_hits = sorted(session_hits, key=lambda hit: hit.relevance, reverse=True)
        entities = []
        for hit in session_hits:
            for entity in hit.memory.entities:
                if entity not in entities:
                    entities.append(entity)
        sessions.append(
            {
                "session_id": str(session_id),
                "is_current_session": session_id == current_session_id,
                "relevance": max(hit.relevance for hit in session_hits),
                "shared_terms": _explain(query_terms, session_hits),
                "entities": entities[:6],
                "memories": [
                    {
                        "memory_id": str(hit.memory.memory_id),
                        "text": hit.memory.text,
                        "type": hit.memory.type.value,
                        "relevance": hit.relevance,
                        "created_at": hit.memory.created_at.isoformat(),
                    }
                    for hit in session_hits[:5]
                ],
            }
        )
    return {
        "reasoning_mode": "heuristic",
        "note": (
            "Correlated by shared terms and entities across your stored memories. "
            "A configured reflection model (for example Nemotron through "
            "MEMORY_REFLECTION_MODEL) can replace this heuristic without changing "
            "how results are shown."
        ),
        "sessions": sessions,
    }


class CorrelationService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("read")
    def correlate(self, ctx, query):
        request = SearchRequest(query=query, top_k=40, score_threshold=0.15)
        hits = self.memory.search(ctx, request)
        return build_correlation(hits, query, current_session_id=ctx.session_id)

    @require_scope("read")
    def conversations(self, ctx, limit=30):
        from sqlalchemy import func, select

        from database import cognitive_tables as c
        from database.repositories.memory import SQLMemoryRepository

        with self.memory.engine.begin() as db:
            SQLMemoryRepository(db, ctx)  # authorize before reading turns
            grouped = (
                db.execute(
                    select(
                        c.turns.c.session_id,
                        func.count().label("turn_count"),
                        func.max(c.turns.c.updated_at).label("last_active_at"),
                    )
                    .where(
                        c.turns.c.namespace_id == ctx.namespace_id,
                        c.turns.c.agent_id == ctx.requesting_agent_id,
                    )
                    .group_by(c.turns.c.session_id)
                    .order_by(func.max(c.turns.c.updated_at).desc())
                    .limit(max(1, min(limit, 100)))
                )
                .mappings()
                .all()
            )
            session_ids = [row["session_id"] for row in grouped]
            labels = {}
            if session_ids:
                first_turn = (
                    select(
                        c.turns.c.session_id,
                        c.turns.c.payload,
                        func.row_number()
                        .over(
                            partition_by=c.turns.c.session_id,
                            order_by=c.turns.c.created_at.asc(),
                        )
                        .label("rank"),
                    )
                    .where(
                        c.turns.c.namespace_id == ctx.namespace_id,
                        c.turns.c.agent_id == ctx.requesting_agent_id,
                        c.turns.c.session_id.in_(session_ids),
                    )
                    .subquery()
                )
                labels = dict(
                    db.execute(
                        select(first_turn.c.session_id, first_turn.c.payload).where(
                            first_turn.c.rank == 1
                        )
                    ).all()
                )
            conversations = []
            for row in grouped:
                first_payload = labels.get(row["session_id"])
                label = ((first_payload or {}).get("message") or "").strip()[:80]
                conversations.append(
                    {
                        "session_id": str(row["session_id"]),
                        "label": label or "New conversation",
                        "turn_count": row["turn_count"],
                        "last_active_at": row["last_active_at"].isoformat(),
                        "is_current_session": row["session_id"] == ctx.session_id,
                    }
                )
            return conversations

    @require_scope("read")
    def turns(self, ctx, session_id, limit=50):
        from sqlalchemy import select

        from database import cognitive_tables as c
        from database.repositories.memory import SQLMemoryRepository

        with self.memory.engine.begin() as db:
            SQLMemoryRepository(db, ctx)  # authorize before reading turns
            rows = (
                db.execute(
                    select(
                        c.turns.c.id,
                        c.turns.c.payload,
                        c.turns.c.response,
                        c.turns.c.status,
                        c.turns.c.created_at,
                    )
                    .where(
                        c.turns.c.namespace_id == ctx.namespace_id,
                        c.turns.c.agent_id == ctx.requesting_agent_id,
                        c.turns.c.session_id == session_id,
                    )
                    .order_by(c.turns.c.created_at.desc())
                    .limit(max(1, min(limit, 200)))
                )
                .mappings()
                .all()
            )
            return [
                {
                    "turn_id": str(row["id"]),
                    "message": (row["payload"] or {}).get("message", ""),
                    "answer": (row["response"] or {}).get("answer"),
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in reversed(rows)
            ]
