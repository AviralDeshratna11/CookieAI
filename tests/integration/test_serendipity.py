import random

from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.experiences.service import ExperienceService
from memory.serendipity.engine import SerendipityEngine


def test_serendipity_returns_none_without_evidence_and_labels_analogy(service, ctx):
    engine = SerendipityEngine(service, rng=random.Random(7))
    assert engine.run(ctx) == []
    for domain in ("software", "workflow"):
        ids = []
        for index in range(4):
            episode = EpisodeService(service).record(
                ctx,
                EpisodeInput(
                    title=f"{domain} contention {index}",
                    trigger="overload",
                    goal="restore flow",
                    context={
                        "goal_type": "restore_flow",
                        "domain": domain,
                        "error_category": "resource_contention",
                        "environment": "production",
                        "workflow_stage": "execution",
                    },
                    outcome="success",
                    attempts=[
                        ToolAttempt(
                            tool="limiter",
                            intent="reduce load",
                            action="limit concurrency",
                            success=True,
                        )
                    ],
                ),
            )
            ids.append(episode.episode_id)
        ExperienceService(service).compile(ctx, ids)
    results = engine.run(ctx)
    assert len(results) == 1
    assert results[0]["type"] == "ANALOGY"
    assert results[0]["epistemic_type"] == "HYPOTHESIZED"
    assert results[0]["differences"]["domain"] == ["software", "workflow"] or results[
        0
    ]["differences"]["domain"] == ["workflow", "software"]
    assert results[0]["causality_status"] == "NONE"
    assert results[0]["critic_verdict"] == "VALIDATED"
