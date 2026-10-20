from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from database import reflection_tables as r
from memory.context.transfer import ContextRequest, ContextTransferService
from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.experiences.service import ExperienceService
from memory.procedures.service import ProcedureCompile, ProcedureService
from memory.reflection.contrastive import ContrastiveDiscovery
from memory.schemas import SearchRequest


def record(service, ctx, environment, outcome, origin="REAL", tool="fixture_checker"):
    # Test records exercise REAL-labeled input handling; these are fixture data,
    # not claims that actual external deployments were observed.
    return EpisodeService(service).record(
        ctx.model_copy(update={"session_id": uuid4()}),
        EpisodeInput(
            event_id=uuid4(),
            title="Fixture task",
            trigger="fixture",
            goal="check deployment",
            context={
                "goal_type": "deploy",
                "domain": "infrastructure",
                "error_category": "fixture",
                "environment": environment,
                "workflow_stage": "validation",
            },
            evidence_origin=origin,
            outcome=outcome,
            attempts=[
                ToolAttempt(
                    tool=tool,
                    intent="check",
                    action="validate fixture",
                    success=outcome == "success",
                )
            ],
        ),
    )


def test_autonomous_procedure_requires_unchanged_conditions(service, ctx, tmp_path):
    from memory.autonomy.contracts import TaskInput
    from memory.autonomy.service import TaskSupervisor
    from memory.goals.service import GoalInput, GoalService

    service.settings.autonomy_enabled = True
    service.settings.autonomy_allowed_agents = [str(ctx.requesting_agent_id)]
    service.settings.hermes_workspace = tmp_path
    episodes = [
        record(service, ctx, "A", "success", tool="cookieai_calculate")
        for _ in range(3)
    ]
    experience = ExperienceService(service).compile(
        ctx, [item.episode_id for item in episodes]
    )
    procedure = ProcedureService(service).compile(
        ctx, ProcedureCompile(experience_ids=[experience.experience_id])
    )
    revision = service.get(ctx, procedure.procedure_id).revision
    goal = UUID(
        GoalService(service).create(
            ctx, GoalInput(title="Fixture approved procedure reuse")
        )["goal_id"]
    )
    supervisor = TaskSupervisor(service)
    base = {
        "goal_id": goal,
        "objective": "Fixture procedure reuse",
        "idempotency_key": uuid4().hex,
        "allowed_tools": ["cookieai_calculate"],
        "steps": [{"tool": "cookieai_calculate", "arguments": {"expression": "2+2"}}],
        "verifier": {"kind": "DECIMAL_RESULT", "expected": "4"},
        "required_procedure_id": procedure.procedure_id,
        "procedure_revision": revision,
        "context_signature": {
            "goal_type": "deploy",
            "domain": "infrastructure",
            "error_category": "fixture",
            "environment": "A",
            "workflow_stage": "validation",
        },
        "evidence_origin": "SYNTHETIC",
    }
    current = supervisor.create(ctx, TaskInput.model_validate(base))
    assert supervisor.process(ctx, UUID(current["task_id"]))["status"] == "COMPLETED"
    changed = supervisor.create(
        ctx,
        TaskInput.model_validate(
            {
                **base,
                "idempotency_key": uuid4().hex,
                "context_signature": {**base["context_signature"], "environment": "B"},
            }
        ),
    )
    assert supervisor.process(ctx, UUID(changed["task_id"]))["status"] == "WAITING"
    assert (
        supervisor.get(ctx, UUID(changed["task_id"]))["state"]["reason"]
        == "ProcedureNotApplicable"
    )


def test_contrastive_candidates_stay_out_of_recall_and_revise(service, ctx, engine):
    episodes = [record(service, ctx, "A", "success") for _ in range(3)]
    episodes += [record(service, ctx, "B", "failure") for _ in range(3)]
    discovery = ContrastiveDiscovery(service)
    result = discovery.run(ctx)
    assert len(result) == 1
    finding = result[0]
    assert finding["status"] == "CANDIDATE" and finding["causal"] is False
    assert finding["observed_counts"]["a"] == {"success": 3, "total": 3}
    assert discovery.run(ctx) == []
    recalled = service.search(
        ctx,
        SearchRequest(
            query="Observed outcome contrast infrastructure", score_threshold=0
        ),
    )
    assert finding["insight_id"] not in {
        str(item.memory.memory_id) for item in recalled
    }
    for _ in range(4):
        record(service, ctx, "A", "failure")
    changed = discovery.run(ctx)
    assert changed[0]["insight_id"] == finding["insight_id"]
    assert changed[0]["status"] == "INVALIDATED"
    service.delete(ctx, episodes[0].episode_id)
    with engine.connect() as db:
        assert not db.execute(
            select(r.insights).where(r.insights.c.id == UUID(finding["insight_id"]))
        ).first()


def test_synthetic_evidence_cannot_activate_real_world_procedure(service, ctx, engine):
    episodes = [record(service, ctx, "A", "success", "REHEARSAL") for _ in range(3)]
    with engine.connect() as db:
        assert not db.execute(select(r.features)).first()
    experience = ExperienceService(service).compile(
        ctx, [episode.episode_id for episode in episodes]
    )
    with pytest.raises(ValueError, match="cannot activate"):
        ProcedureService(service).compile(
            ctx, ProcedureCompile(experience_ids=[experience.experience_id])
        )
    assert ContrastiveDiscovery(service).run(ctx) == []


def test_failure_first_context_keeps_bounded_cautions(service, ctx):
    episode = record(service, ctx, "A", "failure")
    ExperienceService(service).compile(ctx, [episode.episode_id])
    package = ContextTransferService(service).build(
        ctx,
        ContextRequest(
            query="deployment fixture failure",
            context_signature={
                "goal_type": "deploy",
                "domain": "infrastructure",
                "error_category": "fixture",
                "environment": "A",
                "workflow_stage": "validation",
            },
        ),
    )
    assert package["execution_cautions"]
    assert package["execution_cautions"][0]["observed_failure_actions"] == [
        "validate fixture"
    ]
