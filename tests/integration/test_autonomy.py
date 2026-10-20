import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from database import autonomy_tables as a
from database import operations_tables as o
from memory.autonomy.contracts import TaskControl, TaskInput
from memory.autonomy.service import TaskSupervisor
from memory.goals.service import GoalInput, GoalService
from memory.schemas import MemoryCreate, utcnow
from memory.security.auth import AccessDenied, Conflict, NotFound
from workers.runtime import Worker


@pytest.fixture
def supervisor(service, ctx, tmp_path):
    service.settings.autonomy_enabled = True
    service.settings.autonomy_allowed_agents = [str(ctx.requesting_agent_id)]
    service.settings.hermes_workspace = tmp_path
    return TaskSupervisor(service)


@pytest.fixture
def goal(service, ctx):
    return UUID(
        GoalService(service).create(ctx, GoalInput(title="Approved calculation task"))[
            "goal_id"
        ]
    )


def definition(goal, **changes):
    return TaskInput.model_validate(
        {
            "goal_id": goal,
            "objective": "Check an approved arithmetic result",
            "idempotency_key": uuid4().hex,
            "allowed_tools": ["cookieai_calculate"],
            "steps": [
                {"tool": "cookieai_calculate", "arguments": {"expression": "2+2"}}
            ],
            "verifier": {"kind": "DECIMAL_RESULT", "expected": "4"},
            "context_signature": {
                "domain": "arithmetic",
                "goal_type": "check_result",
                "environment": "isolated_test",
            },
            "evidence_origin": "SYNTHETIC",
            **changes,
        }
    )


def drain_until(service, supervisor, ctx, identity, status):
    worker = Worker(service)
    for _ in range(30):
        supervisor.tick(ctx)
        worker.run_once()
        result = supervisor.get(ctx, identity)
        if result["status"] == status:
            return result
    raise AssertionError(result)


@pytest.mark.skipif(
    not os.getenv("COOKIEAI_HERMES_PYTHON"),
    reason="isolated Hermes runtime not selected",
)
def test_real_hermes_supervisor_uses_approved_tools_and_independent_verifier(
    service, supervisor, goal, ctx, monkeypatch, engine
):
    from models.providers import Provider

    service.settings.hermes_enabled = True
    service.settings.hermes_allowed_agents = [str(ctx.requesting_agent_id)]
    service.settings.hermes_python = Path(os.environ["COOKIEAI_HERMES_PYTHON"])
    service.settings.hermes_source = Path(os.environ["COOKIEAI_HERMES_SOURCE"])
    service.settings.hermes_timeout_seconds = 60
    service.settings.assistant_prompt_tokens = 32768
    calls = []

    def post(self, endpoint, payload):
        calls.append(payload)
        assert {tool["function"]["name"] for tool in payload["tools"]} == {
            "cookieai_calculate"
        }
        if len(calls) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "approved-calculation",
                        "type": "function",
                        "function": {
                            "name": "cookieai_calculate",
                            "arguments": '{"expression":"2+2"}',
                        },
                    }
                ],
            }
        else:
            # A false model narrative must not override the receipt-based verifier.
            message = {"role": "assistant", "content": "The task failed; result is 99."}
        return {
            "id": "synthetic-model",
            "object": "chat.completion",
            "created": 0,
            "model": service.settings.extraction_model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls"
                    if message.get("tool_calls")
                    else "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    monkeypatch.setattr(Provider, "post", post)
    task = supervisor.create(
        ctx, definition(goal, backend="hermes", timeout_seconds=60)
    )
    result = supervisor.process(ctx, UUID(task["task_id"]))
    assert result["status"] == "COMPLETED", result
    assert result["verification"]["verdict"] == "PASS"
    assert len(calls) == 2
    with engine.connect() as db:
        usage = db.execute(select(a.usage)).mappings().one()
        assert usage["model_calls"] == 2 and usage["tool_calls"] == 1


def test_worker_schedules_executes_and_verifies_without_model(
    service, supervisor, goal, ctx, engine
):
    body = definition(goal)
    created = supervisor.create(ctx, body)
    identity = UUID(created["task_id"])
    assert supervisor.create(ctx, body)["replayed"]
    supervisor.tick(ctx)
    supervisor.tick(ctx)
    with engine.connect() as db:
        assert (
            db.execute(
                select(func.count())
                .select_from(o.jobs)
                .where(o.jobs.c.queue == "autonomy.run")
            ).scalar_one()
            == 1
        )
    result = drain_until(service, supervisor, ctx, identity, "COMPLETED")
    assert result["runs"][0]["payload"]["verification"]["verdict"] == "PASS"
    assert result["runs"][0]["payload"]["observations"][0]["result"] == {"value": "4"}
    assert result["state"]["runs_used"] == 1
    assert supervisor.process(ctx, identity)["status"] == "COMPLETED"
    assert supervisor.tick(ctx)["scheduled"] == 0
    with pytest.raises(Conflict):
        supervisor.create(ctx, body.model_copy(update={"objective": "different"}))


def test_failed_and_inconclusive_are_not_model_success(supervisor, goal, ctx):
    identity = UUID(
        supervisor.create(
            ctx, definition(goal, verifier={"kind": "DECIMAL_RESULT", "expected": "5"})
        )["task_id"]
    )
    result = supervisor.process(ctx, identity)
    assert result["status"] == "FAILED" and result["verification"]["verdict"] == "FAIL"
    failed = definition(
        goal, steps=[{"tool": "cookieai_calculate", "arguments": {"expression": "1/0"}}]
    )
    identity = UUID(supervisor.create(ctx, failed)["task_id"])
    result = supervisor.process(ctx, identity)
    assert result["verification"]["verdict"] == "INCONCLUSIVE"
    assert result["status"] == "UNCERTAIN"


def test_dependency_wait_and_pause_resume(supervisor, goal, ctx):
    parent = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    child = UUID(
        supervisor.create(
            ctx, definition(goal, depends_on=[parent], parent_task_id=parent)
        )["task_id"]
    )
    assert supervisor.process(ctx, child)["status"] == "WAITING"
    row = supervisor.get(ctx, child)
    paused = supervisor.control(
        ctx, child, TaskControl(action="PAUSE", expected_revision=row["revision"])
    )
    assert supervisor.process(ctx, child)["status"] == "PAUSED"
    supervisor.process(ctx, parent)
    supervisor.control(
        ctx, child, TaskControl(action="RESUME", expected_revision=paused["revision"])
    )
    assert supervisor.process(ctx, child)["status"] == "COMPLETED"


def test_recurrence_and_evaluation_budget(supervisor, goal, ctx, engine):
    identity = UUID(
        supervisor.create(ctx, definition(goal, repeat_seconds=60, max_runs=2))[
            "task_id"
        ]
    )
    assert supervisor.process(ctx, identity)["status"] == "WAITING"
    assert supervisor.process(ctx, identity)["status"] == "WAITING"
    with engine.begin() as db:
        db.execute(
            update(a.tasks)
            .where(a.tasks.c.id == identity)
            .values(next_run_at=utcnow() - timedelta(seconds=1))
        )
    assert supervisor.process(ctx, identity)["status"] == "COMPLETED"
    assert supervisor.get(ctx, identity)["state"]["runs_used"] == 2
    dependency = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    waiting = UUID(
        supervisor.create(
            ctx, definition(goal, depends_on=[dependency], max_evaluations=1)
        )["task_id"]
    )
    assert supervisor.process(ctx, waiting)["status"] == "WAITING"
    with engine.begin() as db:
        db.execute(
            update(a.tasks)
            .where(a.tasks.c.id == waiting)
            .values(next_run_at=utcnow() - timedelta(seconds=1))
        )
    assert supervisor.process(ctx, waiting)["status"] == "EXHAUSTED"


def test_lost_execution_is_reconciled_without_replay(
    service, supervisor, goal, ctx, engine, monkeypatch
):
    from memory.autonomy import service as module

    identity = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    calls = []

    class ProcessDied(BaseException):
        pass

    def die(*args):
        calls.append(1)
        raise ProcessDied()

    monkeypatch.setattr(module, "execute_tool", die)
    with pytest.raises(ProcessDied):
        supervisor.process(ctx, identity)
    with engine.begin() as db:
        db.execute(
            update(a.runs)
            .where(a.runs.c.task_id == identity)
            .values(lease_until=utcnow() - timedelta(seconds=1))
        )
    result = drain_until(service, supervisor, ctx, identity, "UNCERTAIN")
    assert len(calls) == 1
    assert result["runs"][0]["payload"]["observations"][0]["phase"] == "STARTED"


def test_cancellation_and_erasure_fence_late_result(
    service, supervisor, goal, ctx, engine, monkeypatch
):
    from memory.autonomy import service as module

    source = service.create(
        ctx, MemoryCreate(text="Private task evidence", privacy_class="PRIVATE")
    )
    identity = UUID(
        supervisor.create(ctx, definition(goal, evidence_ids=[source.memory_id]))[
            "task_id"
        ]
    )
    original = module.execute_tool

    def erase(*args):
        output = original(*args)
        service.delete(ctx, source.memory_id)
        return output

    monkeypatch.setattr(module, "execute_tool", erase)
    with pytest.raises((AccessDenied, NotFound)):
        supervisor.process(ctx, identity)
    with engine.connect() as db:
        assert not db.execute(select(a.tasks).where(a.tasks.c.id == identity)).first()
        assert not db.execute(
            select(a.runs).where(a.runs.c.task_id == identity)
        ).first()
    other = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    supervisor.control(ctx, other, TaskControl(action="CANCEL", expected_revision=1))
    assert supervisor.process(ctx, other)["status"] == "CANCELLED"


def test_namespace_identity_and_admin_opt_in(service, supervisor, goal, ctx):
    identity = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    with pytest.raises(AccessDenied):
        supervisor.get(
            ctx.model_copy(update={"requesting_agent_id": uuid4()}), identity
        )
    service.settings.autonomy_allowed_agents = []
    with pytest.raises(AccessDenied):
        supervisor.process(ctx, identity)


def test_artifact_verifier_rechecks_actual_file(service, supervisor, goal, ctx):
    import hashlib

    workspace = (
        service.settings.hermes_workspace
        / str(ctx.namespace_id)
        / str(ctx.requesting_agent_id)
    )
    workspace.mkdir(parents=True)
    (workspace / "result.txt").write_text("approved result", encoding="utf-8")
    identity = UUID(
        supervisor.create(
            ctx,
            definition(
                goal,
                allowed_tools=["cookieai_read_text"],
                steps=[
                    {"tool": "cookieai_read_text", "arguments": {"path": "result.txt"}}
                ],
                verifier={
                    "kind": "TEXT_SHA256",
                    "path": "result.txt",
                    "expected": hashlib.sha256(b"approved result").hexdigest(),
                },
            ),
        )["task_id"]
    )
    assert supervisor.process(ctx, identity)["verification"]["verdict"] == "PASS"
    assert "approved result" not in str(supervisor.get(ctx, identity)["runs"])


def test_daily_budget_survives_task_deletion(service, supervisor, goal, ctx, engine):
    service.settings.autonomy_daily_tool_calls = 1
    first = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    assert supervisor.process(ctx, first)["status"] == "COMPLETED"
    service.delete(ctx, first)
    second = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    result = supervisor.process(ctx, second)
    assert (
        result["status"] == "EXHAUSTED" and result["reason"] == "DailyExecutionBudget"
    )
    with engine.connect() as db:
        assert db.execute(select(a.usage.c.tool_calls)).scalar_one() == 1
        assert db.execute(select(func.count()).select_from(a.charges)).scalar_one() == 1


def test_event_activation_is_canonical_deduplicated_and_bounded(
    service, supervisor, goal, ctx, engine
):
    from database import tables as foundation

    created = supervisor.create(
        ctx, definition(goal, trigger="EVENT", event_topics=["release"], max_runs=2)
    )
    identity = UUID(created["task_id"])
    assert created["status"] == "WAITING"
    assert supervisor.tick(ctx)["scheduled"] == 0
    source = service.create(
        ctx, MemoryCreate(text="Approved release observation", topics=["release"])
    )
    with engine.connect() as db:
        event_id = db.execute(
            select(foundation.outbox.c.id).where(
                foundation.outbox.c.object_id == source.memory_id
            )
        ).scalar_one()
    assert supervisor.wake(ctx, uuid4())["activated"] == 0
    assert supervisor.wake(ctx, event_id)["activated"] == 1
    assert supervisor.wake(ctx, event_id)["activated"] == 0
    assert supervisor.process(ctx, identity)["status"] == "WAITING"
    assert supervisor.get(ctx, identity)["next_run_at"] is None
    assert supervisor.tick(ctx)["scheduled"] == 0


def test_canonical_context_correction_blocks_old_approval(
    service, supervisor, goal, ctx
):
    from memory.mutation.engine import MutationRequest

    evidence = service.create(ctx, MemoryCreate(text="Approved environment A"))
    identity = UUID(
        supervisor.create(ctx, definition(goal, evidence_ids=[evidence.memory_id]))[
            "task_id"
        ]
    )
    service.mutate(
        ctx,
        MutationRequest(
            operation="CORRECTION",
            target_id=evidence.memory_id,
            candidate=MemoryCreate(text="Approved environment B"),
            expected_revision=evidence.revision,
        ),
    )
    assert supervisor.process(ctx, identity)["status"] == "WAITING"
    assert supervisor.get(ctx, identity)["state"]["reason"] == "ApprovalRequiresReview"


def test_verified_completion_closes_explicit_goal_and_stops_other_tasks(
    service, supervisor, goal, ctx
):
    first = UUID(
        supervisor.create(ctx, definition(goal, complete_goal_on_success=True))[
            "task_id"
        ]
    )
    second = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    assert supervisor.process(ctx, first)["status"] == "COMPLETED"
    assert (
        next(
            item
            for item in GoalService(service).list(ctx)
            if item["goal_id"] == str(goal)
        )["status"]
        == "COMPLETED"
    )
    assert supervisor.process(ctx, second) == {
        "status": "CANCELLED",
        "reason": "ParentGoalClosed",
    }


def test_recovery_records_failed_attempt_and_verified_success(supervisor, goal, ctx):
    task = supervisor.create(
        ctx,
        definition(
            goal,
            steps=[
                {
                    "tool": "cookieai_calculate",
                    "arguments": {"expression": "1/0"},
                    "on_failure": "CONTINUE",
                },
                {"tool": "cookieai_calculate", "arguments": {"expression": "2+2"}},
            ],
            verifier={"kind": "DECIMAL_RESULT", "step_index": 1, "expected": "4"},
        ),
    )
    identity = UUID(task["task_id"])
    assert supervisor.process(ctx, identity)["verification"]["verdict"] == "PASS"
    run = supervisor.get(ctx, identity)["runs"][0]
    assert [item["success"] for item in run["payload"]["observations"]] == [False, True]
    status = supervisor.status(ctx)
    assert status["task_counts"] == {"COMPLETED": 1}
    assert status["latest_verdict_counts"] == {"PASS": 1}
    assert status["daily_usage"]["tool_calls"] == 2
    assert status["last_completed_task_at"]


def test_changed_precondition_prevents_execution(supervisor, service, goal, ctx):
    workspace = (
        service.settings.hermes_workspace
        / str(ctx.namespace_id)
        / str(ctx.requesting_agent_id)
    )
    workspace.mkdir(parents=True)
    artifact = workspace / "environment.txt"
    artifact.write_text('{"version":"v1"}', encoding="utf-8")
    task = supervisor.create(
        ctx,
        definition(
            goal,
            preconditions=[
                {
                    "kind": "JSON_FIELDS",
                    "path": "environment.txt",
                    "expected": {"version": "v1"},
                }
            ],
        ),
    )
    artifact.write_text('{"version":"v2"}', encoding="utf-8")
    identity = UUID(task["task_id"])
    assert supervisor.process(ctx, identity)["verification"]["verdict"] == "FAIL"
    state = supervisor.get(ctx, identity)
    assert state["state"]["reason"] == "PreconditionNotMet"
    assert state["runs"][0]["payload"]["observations"] == []
    assert supervisor.status(ctx)["daily_usage"]["tool_calls"] == 0


def test_disabled_owner_cannot_starve_later_approved_tasks(
    supervisor, service, goal, ctx
):
    identity = UUID(supervisor.create(ctx, definition(goal))["task_id"])
    service.settings.autonomy_allowed_agents = []
    assert supervisor.tick(ctx)["scheduled"] == 0
    state = supervisor.get(ctx, identity)
    assert state["status"] == "PAUSED"
    assert state["state"]["reason"] == "ExecutionAuthorizationUnavailable"
