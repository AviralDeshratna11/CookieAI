import json
from uuid import uuid4

from sqlalchemy import insert

from database import tables as t
from memory.context.continuity import ContinuityService
from memory.context.transfer import ContextRequest, ContextTransferService
from memory.mutation.engine import MutationKind, MutationRequest
from memory.schemas import MemoryCreate


def test_summary_is_reusable_regenerable_and_erased_with_source(service, ctx):
    source = service.create(
        ctx, MemoryCreate(text="Project Cedar uses PostgreSQL", type="PREFERENCE")
    )
    continuity = ContinuityService(service)
    first = continuity.build(ctx)
    assert continuity.build(ctx) == first
    fresh = ctx.model_copy(update={"session_id": uuid4()})
    packet = ContextTransferService(service).build(
        fresh, ContextRequest(query="Cedar database")
    )
    assert packet["autobiographical_state"]
    assert "PostgreSQL" in json.dumps(packet)
    corrected = service.mutate(
        ctx,
        MutationRequest(
            operation=MutationKind.CORRECTION,
            target_id=source.memory_id,
            expected_revision=1,
            candidate=MemoryCreate(text="Project Cedar now uses SQLite"),
        ),
    )
    assert continuity.load(ctx) == []
    continuity.build(ctx)
    assert "SQLite" in json.dumps(continuity.load(ctx))
    service.delete(ctx, corrected.memory_id)
    assert continuity.load(ctx) == []


def test_summary_permissions_do_not_widen_source_visibility(service, ctx, engine):
    service.create(ctx, MemoryCreate(text="Public Cedar project", entities=["Cedar"]))
    service.create(
        ctx,
        MemoryCreate(text="Private Cedar financial details", privacy_class="PRIVATE"),
    )
    continuity = ContinuityService(service)
    continuity.build(ctx)
    agent = uuid4()
    with engine.begin() as db:
        db.execute(insert(t.agents).values(id=agent, user_id=ctx.user_id))
        db.execute(
            insert(t.grants).values(
                namespace_id=ctx.namespace_id,
                agent_id=agent,
                can_read=True,
                can_write=False,
                can_delete=False,
            )
        )
    receiver = ctx.model_copy(
        update={"requesting_agent_id": agent, "session_id": uuid4()}
    )
    assert "financial" not in json.dumps(continuity.load(receiver))
    assert "Public Cedar" in json.dumps(continuity.load(receiver))
