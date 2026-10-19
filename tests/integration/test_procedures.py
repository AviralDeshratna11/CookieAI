import pytest

from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.experiences.service import ExperienceService
from memory.procedures.service import (
    ProcedureCompile,
    ProcedureFeedback,
    ProcedureService,
)
from memory.schemas import MemoryCreate


def test_repeated_evidence_required_and_failure_feedback_reduces_confidence(
    service, ctx
):
    ids = []
    for i in range(3):
        episode = EpisodeService(service).record(
            ctx,
            EpisodeInput(
                title=f"Incident {i}",
                trigger="release",
                goal="restore",
                context={
                    "error_category": "certificate",
                    "goal_type": "repair",
                    "domain": "infra",
                },
                outcome="success",
                attempts=[
                    ToolAttempt(
                        tool="certbot",
                        intent="renew",
                        action="renew certificate",
                        success=True,
                    )
                ],
            ),
        )
        ids.append(episode.episode_id)
    experiences = ExperienceService(service)
    single = experiences.compile(ctx, ids[:1])
    procedures = ProcedureService(service)
    with pytest.raises(ValueError, match="three independent"):
        procedures.compile(ctx, ProcedureCompile(experience_ids=[single.experience_id]))
    combined = experiences.compile(ctx, ids)
    learned = procedures.compile(
        ctx, ProcedureCompile(experience_ids=[combined.experience_id])
    )
    assert learned.steps == ["renew certificate"]
    failure = service.create(
        ctx,
        MemoryCreate(
            text="Renewal failed under a new condition", epistemic_type="OBSERVED"
        ),
    )
    revised = procedures.feedback(
        ctx,
        learned.procedure_id,
        ProcedureFeedback(success=False, evidence_memory_id=failure.memory_id),
    )
    assert revised.confidence < learned.confidence
    assert revised.failure_count == 1
