from datetime import timedelta

import pytest

from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.experiences.service import ExperienceQuery, ExperienceService
from memory.schemas import utcnow
from memory.security.auth import NotFound


def test_long_range_structural_analogy_and_failed_successful_strategies(service, ctx):
    episode = EpisodeService(service).record(
        ctx,
        EpisodeInput(
            title="Old TLS incident",
            trigger="release",
            goal="restore service",
            context={
                "goal_type": "restore_availability",
                "domain": "infrastructure",
                "error_category": "certificate_validation",
                "environment": "production",
                "workflow_stage": "deployment",
            },
            outcome="success",
            start_time=utcnow() - timedelta(days=120),
            end_time=utcnow() - timedelta(days=119),
            attempts=[
                ToolAttempt(
                    tool="deploy",
                    intent="release",
                    action="retry blindly",
                    success=False,
                    error="TLS",
                ),
                ToolAttempt(
                    tool="certbot",
                    intent="repair",
                    action="renew certificate",
                    success=True,
                ),
            ],
        ),
    )
    experiences = ExperienceService(service)
    experience = experiences.compile(ctx, [episode.episode_id])
    # Different vocabulary, same explicit structure; no shared transcript is needed.
    fresh = ctx.model_copy(update={"session_id": __import__("uuid").uuid4()})
    matches = experiences.search(
        fresh,
        ExperienceQuery(
            query="remote identity chain rejected",
            context_signature={
                "goal_type": "restore_availability",
                "domain": "infrastructure",
                "error_category": "certificate_validation",
                "environment": "production",
                "workflow_stage": "deployment",
            },
        ),
    )
    assert matches[0]["experience"]["experience_id"] == str(experience.experience_id)
    assert "renew certificate" in matches[0]["experience"]["successful_actions"]
    assert "retry blindly" in matches[0]["experience"]["failed_actions"]
    assert matches[0]["similarity"] >= 0.79
    assert experience.confidence <= 0.5
    service.delete(ctx, episode.linked_memory_ids[0])
    with pytest.raises(NotFound):
        experiences.get(ctx, experience.experience_id)
