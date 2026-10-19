from datetime import datetime, timezone

import pytest

from memory.mutation.engine import MutationRequest
from memory.schemas import MemoryCreate, SearchRequest
from memory.security.auth import Conflict


def test_temporal_update_preserves_history(service, ctx):
    old = service.create(
        ctx,
        MemoryCreate(
            text="User lives in Jaipur",
            subject="User",
            predicate="lives in",
            object="Jaipur",
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    new = service.create(
        ctx,
        MemoryCreate(
            text="User lives in Bengaluru",
            subject="User",
            predicate="lives in",
            object="Bengaluru",
            observed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            valid_from=datetime(2026, 4, 1, tzinfo=timezone.utc),
        ),
    )
    previous = service.get(ctx, old.memory_id)
    assert previous.status.value == "SUPERSEDED"
    assert previous.valid_until == new.valid_from
    assert new.supersedes_memory_id == old.memory_id
    assert previous.superseded_by_memory_id == new.memory_id
    hits = service.search(ctx, SearchRequest(query="User lives", score_threshold=0))
    assert [hit.memory.memory_id for hit in hits] == [new.memory_id]


def test_ambiguous_conflict_retains_both_sides(service, ctx):
    old = service.create(
        ctx,
        MemoryCreate(
            text="Alpha uses PostgreSQL",
            subject="Alpha",
            predicate="uses",
            object="PostgreSQL",
        ),
    )
    new = service.create(
        ctx,
        MemoryCreate(
            text="Alpha uses MySQL", subject="Alpha", predicate="uses", object="MySQL"
        ),
    )
    assert (
        service.get(ctx, old.memory_id).status.value == new.status.value == "DISPUTED"
    )
    hits = service.search(
        ctx, SearchRequest(query="Alpha database", top_k=1, score_threshold=0)
    )
    assert {hit.memory.memory_id for hit in hits} == {old.memory_id, new.memory_id}


def test_explicit_correction_uses_revision_and_does_not_destroy_history(service, ctx):
    old = service.create(ctx, MemoryCreate(text="Wrong statement"))
    request = MutationRequest(
        candidate=MemoryCreate(text="Corrected statement"),
        operation="CORRECTION",
        target_id=old.memory_id,
        expected_revision=1,
    )
    new = service.mutate(ctx, request)
    assert new.supersedes_memory_id == old.memory_id
    assert service.get(ctx, old.memory_id).text == "Wrong statement"
    with pytest.raises(Conflict):
        service.mutate(ctx, request)


def test_repeated_reinforcement_does_not_increase_truth(service, ctx):
    proposal = MemoryCreate(text="Repeated statement", truth_confidence=0.4)
    old = service.create(ctx, proposal)
    updated = service.mutate(
        ctx,
        MutationRequest(
            candidate=proposal,
            operation="REINFORCEMENT",
            target_id=old.memory_id,
            expected_revision=1,
        ),
    )
    assert updated.truth_confidence == 0.4
    assert updated.independent_evidence_count == 1
