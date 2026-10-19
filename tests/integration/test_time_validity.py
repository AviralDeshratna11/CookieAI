from datetime import datetime, timedelta, timezone

from memory.schemas import MemoryCreate, SearchRequest, utcnow


def test_future_validity_and_historical_recall(service, ctx):
    service.create(
        ctx,
        MemoryCreate(
            text="Future-only decision", valid_from=utcnow() + timedelta(days=60)
        ),
    )
    assert (
        service.search(ctx, SearchRequest(query="Future-only", score_threshold=0)) == []
    )
    old = service.create(
        ctx,
        MemoryCreate(
            text="User lives Jaipur",
            subject="User",
            predicate="lives",
            object="Jaipur",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    service.create(
        ctx,
        MemoryCreate(
            text="User lives Bengaluru",
            subject="User",
            predicate="lives",
            object="Bengaluru",
            valid_from=datetime(2026, 4, 1, tzinfo=timezone.utc),
            observed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        ),
    )
    hits = service.search(
        ctx,
        SearchRequest(
            query="User lives",
            score_threshold=0,
            as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
    )
    assert [hit.memory.memory_id for hit in hits] == [old.memory_id]
