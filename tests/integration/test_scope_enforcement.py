import pytest
from sqlalchemy import update

from database import tables as t
from memory.schemas import MemoryCreate
from memory.security.auth import AccessDenied


def test_direct_service_delete_cannot_borrow_write_scope(service, ctx, engine):
    memory = service.create(ctx, MemoryCreate(text="protected deletion"))
    with engine.begin() as db:
        db.execute(
            update(t.grants)
            .where(t.grants.c.agent_id == ctx.requesting_agent_id)
            .values(can_delete=False)
        )
    with pytest.raises(AccessDenied):
        service.delete(ctx, memory.memory_id)
    assert service.get(ctx, memory.memory_id)


def test_read_only_agent_cannot_pin_or_create_goal_via_tools(service, ctx, engine):
    from memory.tools import AgentTools

    memory = service.create(ctx, MemoryCreate(text="Read only target"))
    with engine.begin() as db:
        db.execute(
            update(t.grants)
            .where(t.grants.c.agent_id == ctx.requesting_agent_id)
            .values(can_write=False)
        )
    tools = AgentTools(service, ctx.model_copy(update={"requested_scope": "read"}))
    with pytest.raises(AccessDenied):
        tools.memory_pin(str(memory.memory_id))
    from memory.goals.service import GoalInput, GoalService

    with pytest.raises(AccessDenied):
        GoalService(service).create(tools.ctx, GoalInput(title="Unauthorized goal"))
