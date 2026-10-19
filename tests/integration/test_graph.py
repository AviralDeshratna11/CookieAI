import pytest
from sqlalchemy import select

from database import graph_tables as g
from memory.graph.service import EdgeProposal, GraphService
from memory.schemas import MemoryCreate


def test_bounded_activation_cycles_and_deletion(service, ctx, engine):
    memories = [
        service.create(ctx, MemoryCreate(text=f"Observation {i}")) for i in range(5)
    ]
    graph = GraphService(service)
    for left, right in zip(memories, memories[1:] + memories[:1]):
        graph.connect(
            ctx,
            EdgeProposal(
                source_id=left.memory_id,
                target_id=right.memory_id,
                relationship_type="RELATED_TO",
                source_memory_ids=[left.memory_id],
                strength=1,
            ),
        )
    activation = graph.recall(ctx, {memories[0].memory_id: 1})
    assert activation[memories[1].memory_id] == pytest.approx(0.55)
    assert all(0 <= score <= 1 for score in activation.values())
    assert len(activation) <= 5
    service.delete(ctx, memories[0].memory_id)
    with engine.connect() as db:
        assert not db.execute(
            select(g.edges).where(
                (g.edges.c.source_id == memories[0].memory_id)
                | (g.edges.c.target_id == memories[0].memory_id)
            )
        ).first()


def test_correlation_cannot_become_causation(service, ctx):
    left = service.create(ctx, MemoryCreate(text="Event A"))
    right = service.create(ctx, MemoryCreate(text="Event B"))
    with pytest.raises(ValueError, match="causation"):
        GraphService(service).connect(
            ctx,
            EdgeProposal(
                source_id=left.memory_id,
                target_id=right.memory_id,
                relationship_type="CAUSES",
                derivation="STATISTICAL",
                source_memory_ids=[left.memory_id],
            ),
        )
