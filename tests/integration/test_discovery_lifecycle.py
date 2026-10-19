from uuid import uuid4

import pytest

from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.goals.prospective import ProspectiveService
from memory.reflection.engine import ReflectionEngine
from memory.schemas import SearchRequest
from memory.security.auth import Conflict


def event(index, success=False, event_id=None):
    return EpisodeInput(
        event_id=event_id,
        title=f"Independent event {index}",
        trigger="observed test",
        goal="complete task",
        outcome="success" if success else "failure",
        attempts=[
            ToolAttempt(
                tool="ReviewTool",
                intent="run",
                action="execute",
                parameters={"timeout": 5},
                success=success,
            )
        ],
    )


def test_replayed_event_does_not_inflate_independent_support(service, ctx):
    episodes = EpisodeService(service)
    identity = uuid4()
    first = episodes.record(ctx, event(1, event_id=identity))
    assert (
        episodes.record(ctx, event(1, event_id=identity)).episode_id == first.episode_id
    )
    with pytest.raises(Conflict):
        episodes.record(ctx, event(1, success=True, event_id=identity))
    assert ReflectionEngine(service).run(ctx) == []


def test_candidate_is_not_recalled_and_accepted_finding_creates_future_opportunity(
    service, ctx
):
    episodes = EpisodeService(service)
    for index in range(4):
        episodes.record(ctx, event(index))
    reflection = ReflectionEngine(service)
    candidate = reflection.run(ctx)[0]
    assert candidate["status"] == "CANDIDATE"
    assert all(
        str(hit.memory.memory_id) != candidate["insight_id"]
        for hit in service.search(
            ctx,
            SearchRequest(
                query="ReviewTool timeout failure", score_threshold=0, top_k=100
            ),
        )
    )
    for index in range(4, 12):
        episodes.record(ctx, event(index))
    active = reflection.run(ctx)[0]
    assert active["status"] == "ACTIVE"
    matches = ProspectiveService(service).matching(
        ctx, {"context": "ReviewTool deployment"}
    )
    assert len(matches) == 1
    assert active["insight_id"] in matches[0]["provenance_ids"]
    from uuid import UUID

    victim = episodes.get(
        ctx, UUID(active["supporting_episode_ids"][0])
    ).linked_memory_ids[0]
    service.delete(ctx, victim)
    assert reflection.list(ctx, include_candidates=True) == []
    assert (
        ProspectiveService(service).matching(ctx, {"context": "ReviewTool deployment"})
        == []
    )
