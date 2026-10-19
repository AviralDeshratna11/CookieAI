from datetime import timedelta

from memory.decay.service import DynamicsService
from memory.goals.prospective import ProspectiveInput, ProspectiveService
from memory.schemas import MemoryCreate, SearchRequest, utcnow


def test_decay_archives_without_deleting_and_deep_recalls(service, ctx):
    memory = service.create(
        ctx, MemoryCreate(text="Old project Atlas", importance=0.1, salience=0)
    )
    dynamics = DynamicsService(service)
    dynamics.decay(ctx, now=utcnow() + timedelta(days=1500))
    archived = service.get(ctx, memory.memory_id)
    assert archived.status.value == "ARCHIVED"
    assert archived.truth_confidence == memory.truth_confidence
    assert service.search(ctx, SearchRequest(query="Atlas", score_threshold=0)) == []
    assert service.search(
        ctx, SearchRequest(query="Atlas", score_threshold=0, mode="DEEP")
    )


def test_pinned_records_and_prospective_triggers(service, ctx):
    memory = service.create(ctx, MemoryCreate(text="Pinned decision"))
    dynamics = DynamicsService(service)
    dynamics.pin(ctx, memory.memory_id)
    dynamics.decay(ctx, now=utcnow() + timedelta(days=1500))
    assert service.get(ctx, memory.memory_id).status.value == "ACTIVE"
    prospective = ProspectiveService(service)
    prospective.create(
        ctx,
        ProspectiveInput(
            trigger_type="ENTITY",
            trigger={"value": "Atlas"},
            action_or_memory="Check migration procedure",
        ),
    )
    assert prospective.activate(ctx, {"entity": "Unrelated"}) == []
    assert len(prospective.activate(ctx, {"entity": "Atlas"})) == 1
    assert prospective.activate(ctx, {"entity": "Atlas"}) == []


def test_clusters_have_provenance_and_disappear_with_evidence(service, ctx):
    first = service.create(
        ctx, MemoryCreate(text="Alpha database PostgreSQL", entities=["Alpha"])
    )
    service.create(
        ctx, MemoryCreate(text="Alpha deploy uses migrations", entities=["Alpha"])
    )
    clusters = DynamicsService(service).cluster(ctx)
    assert len(clusters) == 1
    cluster_id = __import__("uuid").UUID(clusters[0]["cluster_id"])
    assert first.memory_id in service.get(ctx, cluster_id).provenance_ids
    service.delete(ctx, first.memory_id)
    import pytest

    from memory.security.auth import NotFound

    with pytest.raises(NotFound):
        service.get(ctx, cluster_id)
