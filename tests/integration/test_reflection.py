from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.reflection.engine import ReflectionEngine


def seed(service, ctx, count, success, start=0):
    episodes = EpisodeService(service)
    for index in range(start, start + count):
        episodes.record(
            ctx,
            EpisodeInput(
                title=f"Run {index}",
                trigger="test",
                goal="complete job",
                outcome="success" if success else "failure",
                attempts=[
                    ToolAttempt(
                        tool="ToolX",
                        parameters={"configuration": "Y"},
                        intent="run",
                        action="execute",
                        success=success,
                    )
                ],
            ),
        )


def test_counterevidence_revises_confidence_and_incremental_cursor(service, ctx):
    seed(service, ctx, 4, False)
    reflection = ReflectionEngine(service)
    first = reflection.run(ctx)[0]
    assert first["status"] == "CANDIDATE"
    assert first["truth_confidence"] < 0.65
    assert reflection.run(ctx) == []
    seed(service, ctx, 7, True, start=4)
    revised = reflection.run(ctx)[0]
    assert revised["insight_id"] == first["insight_id"]
    assert revised["truth_confidence"] < first["truth_confidence"]
    assert revised["status"] == "DISPUTED"
    assert revised["counterexample_count"] == 7
    assert revised["causality_status"] == "NONE"


def test_small_sample_rejected_and_100_episode_hidden_pattern_detected(service, ctx):
    seed(service, ctx, 2, False)
    reflection = ReflectionEngine(service)
    assert reflection.run(ctx) == []
    seed(service, ctx, 78, False, start=2)
    seed(service, ctx, 20, True, start=80)
    insight = reflection.run(ctx)[0]
    assert insight["support_count"] == 80
    assert insight["counterexample_count"] == 20
    assert insight["status"] == "ACTIVE"
    assert insight["critic_verdict"] == "VALIDATED"
    assert insight["epistemic_type"] == "CORRELATED"
