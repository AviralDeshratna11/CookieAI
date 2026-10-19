from datetime import timedelta
from uuid import uuid4

from memory.decay.service import DynamicsService
from memory.reflection.engine import ReflectionEngine
from memory.reflection.structured import StructuredDiscovery
from memory.schemas import MemoryCreate, RememberRequest, utcnow


def test_structured_support_counterevidence_and_replay(service, ctx):
    for number in range(6):
        service.create(
            ctx.model_copy(update={"session_id": uuid4()}),
            MemoryCreate(
                text=f"Meeting {number}: Mira prefers short reports",
                subject="Mira",
                predicate="prefers",
                object="short reports",
            ),
        )
    miner = StructuredDiscovery(service)
    first = miner.run(ctx)
    assert len(first) == 1 and first[0]["status"] == "ACTIVE"
    identity = first[0]["insight_id"]
    assert miner.run(ctx) == []
    for number in range(6):
        service.create(
            ctx.model_copy(update={"session_id": uuid4()}),
            MemoryCreate(
                text=f"Workshop {number}: Mira prefers detailed reports",
                subject="Mira",
                predicate="prefers",
                object="detailed reports",
            ),
        )
    revised = next(item for item in miner.run(ctx) if item["insight_id"] == identity)
    assert revised["status"] in {"DISPUTED", "INVALIDATED"}
    assert revised["truth_confidence"] < first[0]["truth_confidence"]
    assert revised["state_history"]


def test_replayed_ingestion_without_generated_fields_does_not_resurrect(service, ctx):
    raw = {
        "messages": [{"role": "user", "content": "Unique private observation"}],
        "mode": "raw",
        "idempotency_key": "private observation key",
    }
    first = service.remember(ctx, RememberRequest.model_validate(raw))
    again = service.remember(ctx, RememberRequest.model_validate(raw))
    assert [m.memory_id for m in first] == [m.memory_id for m in again]
    service.delete(ctx, first[0].memory_id)
    assert service.remember(ctx, RememberRequest.model_validate(raw)) == []


def test_candidate_retention_expires_both_canonical_and_finding(service, ctx):
    for index in range(3):
        service.create(
            ctx.model_copy(update={"session_id": uuid4()}),
            MemoryCreate(
                text=f"Source {index} mentions Project Cedar and Project Maple together",
                entities=["Project Cedar", "Project Maple"],
            ),
        )
    candidate = StructuredDiscovery(service).run(ctx)[0]
    assert candidate["status"] == "CANDIDATE"
    DynamicsService(service).decay(ctx, now=utcnow() + timedelta(days=31))
    assert ReflectionEngine(service).list(ctx, include_candidates=True) == []
