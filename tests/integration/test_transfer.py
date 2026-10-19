import json
from uuid import uuid4

import pytest
from sqlalchemy import insert

from database import tables as t
from memory.context.transfer import ContextRequest, ContextTransferService
from memory.goals.service import GoalInput, GoalPatch, GoalService
from memory.schemas import MemoryCreate
from memory.security.auth import AccessDenied


def test_empty_session_and_authorized_b_denied_c_context(service, ctx, engine):
    service.create(
        ctx,
        MemoryCreate(text="Project Alpha uses PostgreSQL", entities=["Project Alpha"]),
    )
    service.create(ctx, MemoryCreate(text="Private secret", privacy_class="PRIVATE"))
    agent_b = uuid4()
    with engine.begin() as db:
        db.execute(insert(t.agents).values(id=agent_b, user_id=ctx.user_id))
        db.execute(
            insert(t.grants).values(
                namespace_id=ctx.namespace_id,
                agent_id=agent_b,
                can_read=True,
                can_write=False,
                can_delete=False,
            )
        )
    fresh = ctx.model_copy(update={"session_id": uuid4(), "requested_scope": "read"})
    transfer = ContextTransferService(service)
    packet = transfer.build(fresh, ContextRequest(query="Alpha database"))
    assert "PostgreSQL" in json.dumps(packet)
    assert packet["active_projects"][0]["name"] == "Project Alpha"
    assert len(json.dumps(packet, ensure_ascii=False).encode()) <= 8000
    packet_b = transfer.transfer(
        fresh, ContextRequest(query="Alpha database", target_agent_id=agent_b)
    )
    assert "PostgreSQL" in json.dumps(packet_b)
    assert "Private secret" not in json.dumps(packet_b)
    with pytest.raises(AccessDenied):
        transfer.transfer(fresh, ContextRequest(query="Alpha", target_agent_id=uuid4()))


def test_goals_persist_progress_and_bootstrap(service, ctx):
    goals = GoalService(service)
    goal = goals.create(ctx, GoalInput(title="Ship Alpha", priority=0.9))
    revised = goals.patch(
        ctx,
        __import__("uuid").UUID(goal["goal_id"]),
        GoalPatch(expected_revision=1, progress=0.6, status="BLOCKED"),
    )
    packet = ContextTransferService(service).build(ctx, ContextRequest(query="Alpha"))
    assert packet["active_goals"][0]["progress"] == 0.6
    assert revised["revision"] == 2
