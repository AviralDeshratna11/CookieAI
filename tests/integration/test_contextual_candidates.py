from datetime import timedelta

from memory.schemas import MemoryCreate, SearchRequest, utcnow


def test_temporal_and_goal_generators_have_distinct_explanations(service, ctx):
    goal = service.create(ctx, MemoryCreate(text="Alpha migration", type="GOAL"))
    memory = service.create(
        ctx,
        MemoryCreate(
            text="Alpha migration strategy", event_at=utcnow() - timedelta(days=1)
        ),
    )
    hits = service.search(
        ctx,
        SearchRequest(
            query="past work",
            active_goal_id=goal.memory_id,
            time_start=utcnow() - timedelta(days=2),
            time_end=utcnow(),
            score_threshold=0,
        ),
    )
    selected = next(hit for hit in hits if hit.memory.memory_id == memory.memory_id)
    assert selected.why_retrieved["goal"] > 0
    assert selected.why_retrieved["temporal"] == 1
