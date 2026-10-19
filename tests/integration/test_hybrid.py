from sqlalchemy import func, select

from database import hybrid_tables as h
from memory.context.composer import compose
from memory.schemas import MemoryCreate, SearchRequest


def test_lexical_can_add_outside_vector_pool(service, ctx, monkeypatch):
    from database.repositories.memory import SQLMemoryRepository

    target = service.create(
        ctx,
        MemoryCreate(text="Project Obscure migration", entities=["Project Obscure"]),
    )
    # Simulate a dense generator that missed the item entirely.
    monkeypatch.setattr(SQLMemoryRepository, "search", lambda *args, **kwargs: [])
    hits = service.search(
        ctx, SearchRequest(query="Obscure migration", score_threshold=0)
    )
    assert hits[0].memory.memory_id == target.memory_id
    assert hits[0].why_retrieved["semantic"] == 0
    assert hits[0].why_retrieved["keyword"] > 0


def test_three_store_projection_and_entity_cleanup(service, ctx, engine):
    memory = service.create(
        ctx,
        MemoryCreate(
            text="Project Alpha uses PostgreSQL",
            entities=["Project Alpha", "PostgreSQL"],
        ),
    )
    with engine.connect() as db:
        assert db.execute(select(func.count()).select_from(h.entities)).scalar() == 2
        assert (
            db.execute(select(func.count()).select_from(h.entity_embeddings)).scalar()
            == 2
        )
        assert (
            db.execute(select(func.count()).select_from(h.memory_entities)).scalar()
            == 2
        )
        assert db.execute(select(h.lexical.c.terms)).scalar() == [
            "project",
            "alpha",
            "use",
            "postgresql",
        ]
    service.delete(ctx, memory.memory_id)
    with engine.connect() as db:
        for table in (
            h.entities,
            h.entity_embeddings,
            h.entity_aliases,
            h.memory_entities,
            h.lexical,
        ):
            assert db.execute(select(func.count()).select_from(table)).scalar() == 0


def test_context_separates_statements_from_facts_and_enforces_budget(service, ctx):
    service.create(ctx, MemoryCreate(text="Alpha uses PostgreSQL"))
    hits = service.search(
        ctx, SearchRequest(query="Alpha PostgreSQL", score_threshold=0)
    )
    packet = compose(hits, 1000)
    assert len(packet.model_dump_json().encode()) <= 1000
    assert not packet.confirmed_facts
    assert packet.user_statements[0]["epistemic_type"] == "USER_STATED"
    assert "Untrusted" in packet.trust


def test_entity_specificity_uses_inverse_permitted_fanout(service, ctx):
    rare = service.create(
        ctx, MemoryCreate(text="Unusual migration", entities=["Zephyr"])
    )
    for index in range(4):
        service.create(
            ctx, MemoryCreate(text=f"Ordinary note {index}", entities=["Common"])
        )
    rare_hits = service.search(
        ctx, SearchRequest(query="Zephyr", score_threshold=0, top_k=10)
    )
    common_hits = service.search(
        ctx, SearchRequest(query="Common", score_threshold=0, top_k=10)
    )
    rare_score = next(
        hit.why_retrieved["entity"]
        for hit in rare_hits
        if hit.memory.memory_id == rare.memory_id
    )
    common_score = max(hit.why_retrieved["entity"] for hit in common_hits)
    assert rare_score > common_score
