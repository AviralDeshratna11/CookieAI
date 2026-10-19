"""Exact names resolve; approximate similarity alone never permanently merges entities."""

import math
import re
from uuid import uuid4

from sqlalchemy import delete, insert, select

from database import hybrid_tables as h
from memory.retrieval.hybrid import terms


def names(memory):
    explicit = memory.entities
    inferred = re.findall(
        r"\b(?:Project\s+[A-Z][\w-]*|[A-Z][a-z]+(?:[A-Z][\w]*)+)\b", memory.text
    )
    return list(
        dict.fromkeys(
            name.strip() for name in explicit + inferred if 0 < len(name.strip()) <= 500
        )
    )[:100]


def project(repo, memory, embedder):
    db = repo.db
    db.execute(delete(h.lexical).where(h.lexical.c.memory_id == memory.memory_id))
    db.execute(
        insert(h.lexical).values(
            memory_id=memory.memory_id, terms=terms(memory.canonical_text)
        )
    )
    db.execute(
        delete(h.memory_entities).where(
            h.memory_entities.c.memory_id == memory.memory_id
        )
    )
    for name in names(memory):
        normalized = " ".join(name.casefold().split())
        entity_id = db.execute(
            select(h.entities.c.id).where(
                h.entities.c.namespace_id == memory.namespace_id,
                h.entities.c.normalized_name == normalized,
            )
        ).scalar()
        if entity_id is None:
            entity_id = uuid4()
            db.execute(
                insert(h.entities).values(
                    id=entity_id,
                    namespace_id=memory.namespace_id,
                    canonical_name=name,
                    normalized_name=normalized,
                    entity_type="PROJECT"
                    if normalized.startswith("project ")
                    else "CONCEPT",
                    resolution_confidence=1.0,
                )
            )
            db.execute(
                insert(h.entity_aliases).values(entity_id=entity_id, alias=normalized)
            )
            vector = embedder.embed(name)
            db.execute(
                insert(h.entity_embeddings).values(
                    entity_id=entity_id,
                    model_id=embedder.model_id,
                    model_version=embedder.version,
                    dimensions=embedder.dimensions,
                    vector=vector,
                )
            )
        db.execute(
            insert(h.memory_entities).values(
                memory_id=memory.memory_id, entity_id=entity_id
            )
        )


def scores(repo, query, query_vector, permitted_ids, model):
    rows = repo.db.execute(
        select(h.entities, h.entity_embeddings.c.vector, h.memory_entities.c.memory_id)
        .join(h.entity_embeddings)
        .join(h.memory_entities)
        .where(
            h.entities.c.namespace_id == repo.ctx.namespace_id,
            h.memory_entities.c.memory_id.in_(permitted_ids),
            h.entity_embeddings.c.model_id == model.model_id,
            h.entity_embeddings.c.model_version == model.version,
            h.entity_embeddings.c.dimensions == model.dimensions,
        )
    ).mappings()
    matched = {}
    for row in rows:
        query_terms = set(terms(query))
        exact = set(terms(row["canonical_name"])).issubset(query_terms)
        cosine = sum(a * float(b) for a, b in zip(query_vector, row["vector"]))
        if exact or cosine >= 0.90:
            matched.setdefault(row["id"], set()).add(row["memory_id"])
    result = {}
    for links in matched.values():
        specificity = min(1.0, 1 / math.log(2 + len(links)))
        for memory_id in links:
            result[memory_id] = max(result.get(memory_id, 0), specificity)
    return result


def remove_orphans(db, namespace_id):
    linked = select(h.memory_entities.c.entity_id)
    ids = list(
        db.execute(
            select(h.entities.c.id).where(
                h.entities.c.namespace_id == namespace_id, ~h.entities.c.id.in_(linked)
            )
        ).scalars()
    )
    if ids:
        from database import graph_tables as graph

        db.execute(delete(graph.nodes).where(graph.nodes.c.id.in_(ids)))
        db.execute(
            delete(h.entity_aliases).where(h.entity_aliases.c.entity_id.in_(ids))
        )
        db.execute(
            delete(h.entity_embeddings).where(h.entity_embeddings.c.entity_id.in_(ids))
        )
        db.execute(delete(h.entities).where(h.entities.c.id.in_(ids)))
