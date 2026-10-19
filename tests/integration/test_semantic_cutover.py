import pytest
from sqlalchemy import select

from apps.cli.reindex import reindex_namespace
from database import hybrid_tables as h
from database import tables as t
from memory.schemas import MemoryCreate
from models.providers import HashEmbedding


def test_cutover_can_join_an_outer_rollback(service, ctx):
    original = service.create(ctx, MemoryCreate(text="Outer transaction test"))

    class Target(HashEmbedding):
        model_id = "atomic-target"
        version = "3"

    with service.engine.connect() as db:
        transaction = db.begin()
        assert reindex_namespace(service.engine, ctx, Target(32), connection=db) == 1
        transaction.rollback()
    assert service.get(ctx, original.memory_id).embedding_model == "hash-test"


def test_cutover_rolls_back_and_resumes_without_losing_canonical_data(service, ctx):
    first = service.create(ctx, MemoryCreate(text="Project Aurora uses PostgreSQL"))
    second = service.create(ctx, MemoryCreate(text="Project Borealis uses Redis"))

    class Target(HashEmbedding):
        model_id = "target"
        version = "2"

    class Failing(Target):
        def embed(self, text):
            if "Borealis" in text:
                raise RuntimeError("provider unavailable")
            return super().embed(text)

    with pytest.raises(RuntimeError):
        reindex_namespace(service.engine, ctx, Failing(32))
    assert service.get(ctx, first.memory_id).embedding_model == "hash-test"
    with service.engine.connect() as db:
        assert set(db.execute(select(t.embeddings.c.dimensions)).scalars()) == {64}
    assert reindex_namespace(service.engine, ctx, Target(32)) == 2
    assert reindex_namespace(service.engine, ctx, Target(32)) == 0
    for memory in (first, second):
        current = service.get(ctx, memory.memory_id)
        assert current.text == memory.text
        assert current.embedding_model == "target"
    with service.engine.connect() as db:
        assert set(db.execute(select(h.entity_embeddings.c.dimensions)).scalars()) == {
            32
        }
