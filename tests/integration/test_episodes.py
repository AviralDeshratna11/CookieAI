from datetime import timedelta

import pytest

from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.schemas import MemoryCreate, SearchRequest, utcnow
from memory.security.auth import NotFound


def test_episode_tool_failures_and_successes_preserved(service, ctx):
    episodes = EpisodeService(service)
    episode = episodes.record(
        ctx,
        EpisodeInput(
            title="TLS incident",
            trigger="deployment",
            goal="restore service",
            context={
                "domain": "infrastructure",
                "error_category": "certificate_validation",
            },
            outcome="success",
            attempts=[
                ToolAttempt(
                    tool="deploy",
                    intent="release",
                    action="retry deploy",
                    success=False,
                    error="TLS mismatch",
                ),
                ToolAttempt(
                    tool="certbot",
                    intent="renew",
                    action="renew certificate",
                    success=True,
                    result="valid",
                ),
            ],
        ),
    )
    recalled = episodes.get(ctx, episode.episode_id)
    assert recalled.attempts[0].error == "TLS mismatch"
    assert recalled.attempts[1].success
    assert len(recalled.linked_memory_ids) == 3
    assert service.get(ctx, episode.episode_id).epistemic_type.value == "INFERRED"
    assert episodes.search(ctx, SearchRequest(query="TLS incident", score_threshold=0))
    service.delete(ctx, episode.linked_memory_ids[0])
    with pytest.raises(NotFound):
        episodes.get(ctx, episode.episode_id)


def test_segmentation_splits_session_and_time_boundaries(service, ctx):
    first = service.create(
        ctx,
        MemoryCreate(
            text="Morning decision", observed_at=utcnow() - timedelta(hours=2)
        ),
    )
    second = service.create(ctx, MemoryCreate(text="Afternoon decision"))
    groups = EpisodeService(service).segment(ctx, [first.memory_id, second.memory_id])
    assert len(groups) == 2


def test_episode_without_observations_rejected(service, ctx):
    with pytest.raises(ValueError, match="actual atomic"):
        EpisodeService(service).record(
            ctx, EpisodeInput(title="invented", trigger="none", goal="none")
        )
