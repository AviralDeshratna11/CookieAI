from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, or_, select

from database import graph_tables as g
from database import hybrid_tables as h
from database.repositories.memory import SQLMemoryRepository
from memory.schemas import Field, Score, StrictModel, utcnow
from memory.security.auth import NotFound, require_scope

RELATIONSHIPS = set(
    "MENTIONS RELATED_TO PART_OF INVOLVES BELONGS_TO PRECEDES FOLLOWS OCCURRED_DURING CAUSES POSSIBLY_CAUSES CORRELATES_WITH CONTRADICTS SUPPORTS REFINES SUPERSEDES DERIVED_FROM SIMILAR_TO ANALOGOUS_TO WORKED_FOR FAILED_FOR DEPENDS_ON BLOCKED_BY ENABLES PREFERS DISLIKES LOCATED_AT USED_WITH RESULTED_IN CO_OCCURS_WITH PREDICTS POSSIBLY_SAME_AS".split()
)


class EdgeProposal(StrictModel):
    source_id: UUID
    target_id: UUID
    relationship_type: str
    confidence: Score = 0.5
    strength: Score = 0.5
    source_memory_ids: list[UUID] = Field(min_length=1, max_length=100)
    derivation: Literal[
        "EXPLICIT", "RULE", "STATISTICAL", "LLM", "GRAPH", "USER_CONFIRMED"
    ] = "RULE"


def node(repo, object_id, kind):
    existing = (
        repo.db.execute(select(g.nodes).where(g.nodes.c.id == object_id))
        .mappings()
        .first()
    )
    if existing:
        if existing["namespace_id"] != repo.ctx.namespace_id:
            raise ValueError("graph node crosses namespace")
        return
    repo.db.execute(
        insert(g.nodes).values(
            id=object_id, namespace_id=repo.ctx.namespace_id, kind=kind
        )
    )


def permitted(repo, object_id):
    try:
        repo.get(object_id)
        return True
    except NotFound:
        for memory_id in repo.db.execute(
            select(h.memory_entities.c.memory_id).where(
                h.memory_entities.c.entity_id == object_id
            )
        ).scalars():
            try:
                repo.get(memory_id)
                return True
            except NotFound:
                pass
    return False


def add_edge(repo, proposal):
    if proposal.relationship_type not in RELATIONSHIPS:
        raise ValueError("unknown graph relation")
    if not permitted(repo, proposal.source_id) or not permitted(
        repo, proposal.target_id
    ):
        raise NotFound("graph endpoint not found")
    evidence = [repo.get(item) for item in proposal.source_memory_ids]
    if proposal.relationship_type == "CAUSES" and (
        proposal.derivation not in {"EXPLICIT", "USER_CONFIRMED"}
        or any(
            item.epistemic_type.value
            in {"INFERRED", "CORRELATED", "HYPOTHESIZED", "PREDICTED"}
            for item in evidence
        )
    ):
        raise ValueError("derived association cannot establish causation")
    for endpoint in (proposal.source_id, proposal.target_id):
        try:
            node(repo, endpoint, repo.get(endpoint).type.value)
        except NotFound:
            node(repo, endpoint, "ENTITY")
    existing = repo.db.execute(
        select(g.edges.c.id).where(
            g.edges.c.namespace_id == repo.ctx.namespace_id,
            g.edges.c.source_id == proposal.source_id,
            g.edges.c.target_id == proposal.target_id,
            g.edges.c.relationship_type == proposal.relationship_type,
        )
    ).scalar()
    if existing:
        return existing
    edge_id = uuid4()
    payload = proposal.model_dump(mode="json")
    payload.update(
        edge_id=str(edge_id),
        evidence_count=len(set(proposal.source_memory_ids)),
        first_seen=utcnow().isoformat(),
        last_seen=utcnow().isoformat(),
    )
    repo.db.execute(
        insert(g.edges).values(
            id=edge_id,
            namespace_id=repo.ctx.namespace_id,
            source_id=proposal.source_id,
            target_id=proposal.target_id,
            relationship_type=proposal.relationship_type,
            payload=payload,
        )
    )
    for source_id in set(proposal.source_memory_ids):
        repo.db.execute(
            insert(g.edge_evidence).values(edge_id=edge_id, memory_id=source_id)
        )
    return edge_id


def sync(repo, memory):
    node(repo, memory.memory_id, memory.type.value)
    for entity_id in repo.db.execute(
        select(h.memory_entities.c.entity_id).where(
            h.memory_entities.c.memory_id == memory.memory_id
        )
    ).scalars():
        node(repo, entity_id, "ENTITY")
        add_edge(
            repo,
            EdgeProposal(
                source_id=memory.memory_id,
                target_id=entity_id,
                relationship_type="MENTIONS",
                strength=1,
                confidence=1,
                source_memory_ids=[memory.memory_id],
                derivation="EXPLICIT",
            ),
        )
    for parent in memory.provenance_ids:
        add_edge(
            repo,
            EdgeProposal(
                source_id=memory.memory_id,
                target_id=parent,
                relationship_type="DERIVED_FROM",
                confidence=1,
                strength=0.8,
                source_memory_ids=[parent],
                derivation="RULE",
            ),
        )


def activation(
    repo,
    seeds,
    max_hops=3,
    hop_decay=0.55,
    minimum=0.10,
    max_nodes=500,
    permitted_memory_ids=None,
):
    if permitted_memory_ids is None:
        from database import tables as foundation
        from memory.schemas import Memory

        permitted_memory_ids = {
            item.memory_id
            for row in repo.db.execute(
                select(foundation.memories.c.payload).where(
                    foundation.memories.c.namespace_id == repo.ctx.namespace_id,
                    foundation.memories.c.owner_id == repo.ctx.user_id,
                )
            )
            if repo.allowed(item := Memory.model_validate(row.payload))
        }
    visible_memories = set(permitted_memory_ids)
    visible_entities = set(
        repo.db.execute(
            select(h.memory_entities.c.entity_id).where(
                h.memory_entities.c.memory_id.in_(visible_memories)
            )
        ).scalars()
    )
    visible_nodes = visible_memories | visible_entities
    activated = {key: score for key, score in seeds.items() if key in visible_nodes}
    frontier = dict(activated)
    visited = set()
    for _ in range(min(3, max(0, max_hops))):
        # Fetch only incident edges for this hop. Partition the frontier to stay
        # below database parameter limits; do not scan every namespace edge.
        edges = {}
        frontier_ids = sorted(set(frontier) - visited, key=str)
        for offset in range(0, len(frontier_ids), 200):
            batch = frontier_ids[offset : offset + 200]
            rows = repo.db.execute(
                select(g.edges).where(
                    g.edges.c.namespace_id == repo.ctx.namespace_id,
                    or_(g.edges.c.source_id.in_(batch), g.edges.c.target_id.in_(batch)),
                )
            ).mappings()
            for row in rows:
                if (
                    row["source_id"] in visible_nodes
                    and row["target_id"] in visible_nodes
                    and all(
                        UUID(item) in visible_memories
                        for item in row["payload"]["source_memory_ids"]
                    )
                ):
                    edges[row["id"]] = row
        next_frontier = {}
        for current, score in frontier.items():
            if current in visited:
                continue
            visited.add(current)
            for edge in edges.values():
                if edge["source_id"] == current:
                    target = edge["target_id"]
                elif edge["target_id"] == current:
                    target = edge["source_id"]
                else:
                    continue
                if target in visited:
                    continue
                value = score * edge["payload"]["strength"] * hop_decay
                if (
                    value >= minimum
                    and value > activated.get(target, 0)
                    and len(activated) < max_nodes
                ):
                    activated[target] = value
                    next_frontier[target] = max(next_frontier.get(target, 0), value)
        frontier = next_frontier
    return activated


def remove(repo, memory_ids):
    edge_ids = select(g.edge_evidence.c.edge_id).where(
        g.edge_evidence.c.memory_id.in_(memory_ids)
    )
    repo.db.execute(delete(g.edges).where(g.edges.c.id.in_(edge_ids)))
    repo.db.execute(delete(g.nodes).where(g.nodes.c.id.in_(memory_ids)))


class GraphService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def connect(self, ctx, proposal):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            return add_edge(repo, proposal)

    @require_scope("read")
    def recall(self, ctx, seeds):
        with self.memory.engine.begin() as connection:
            return activation(SQLMemoryRepository(connection, ctx), seeds)
