from sqlalchemy import select

from database import hybrid_tables as h
from database.repositories.memory import SQLMemoryRepository
from memory.retrieval.hybrid import terms
from memory.security.auth import NotFound


class EntityService:
    def __init__(self, memory):
        self.memory = memory

    def get(self, ctx, entity_id):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(
                db, ctx.model_copy(update={"requested_scope": "read"})
            )
            row = (
                db.execute(
                    select(h.entities).where(
                        h.entities.c.id == entity_id,
                        h.entities.c.namespace_id == ctx.namespace_id,
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound("entity not found")
            visible = []
            for memory_id in db.execute(
                select(h.memory_entities.c.memory_id).where(
                    h.memory_entities.c.entity_id == entity_id
                )
            ).scalars():
                try:
                    repo.get(memory_id)
                except NotFound:
                    continue
                visible.append(str(memory_id))
            if not visible:
                raise NotFound("entity not found")
            aliases = list(
                db.execute(
                    select(h.entity_aliases.c.alias).where(
                        h.entity_aliases.c.entity_id == entity_id
                    )
                ).scalars()
            )
            return {
                "entity_id": str(entity_id),
                "canonical_name": row["canonical_name"],
                "entity_type": row["entity_type"],
                "aliases": aliases,
                "resolution_confidence": row["resolution_confidence"],
                "linked_memory_ids": visible,
            }

    def search(self, ctx, request):
        from memory.graph.service import permitted

        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(
                db, ctx.model_copy(update={"requested_scope": "read"})
            )
            vector = self.memory.vector(request.query)
            rows = db.execute(
                select(h.entities, h.entity_embeddings.c.vector)
                .join(h.entity_embeddings)
                .where(
                    h.entities.c.namespace_id == ctx.namespace_id,
                    h.entity_embeddings.c.model_id == self.memory.embedder.model_id,
                    h.entity_embeddings.c.model_version == self.memory.embedder.version,
                    h.entity_embeddings.c.dimensions == self.memory.embedder.dimensions,
                )
            ).mappings()
            selected = []
            for row in rows:
                if not permitted(repo, row["id"]):
                    continue
                similarity = max(
                    0, min(1, sum(a * float(b) for a, b in zip(vector, row["vector"])))
                )
                if set(terms(row["canonical_name"])).issubset(
                    set(terms(request.query))
                ):
                    similarity = 1
                if similarity >= request.score_threshold:
                    selected.append((row["id"], similarity))
        return [
            {"entity": self.get(ctx, item), "relevance": score}
            for item, score in sorted(selected, key=lambda pair: -pair[1])[
                : request.top_k
            ]
        ]
