from uuid import UUID, uuid4

import pytest

from database.repositories.memory import SQLMemoryRepository
from memory.retrieval.correlation import CorrelationService
from memory.schemas import MemoryCreate, MemoryPatch, RequestContext
from memory.security.auth import AccessDenied
from memory.sharing.service import ShareInput, SharingService
from tests.conftest import provision


@pytest.fixture
def grantee(engine):
    ctx = RequestContext(
        user_id=uuid4(),
        requesting_agent_id=uuid4(),
        namespace_id=uuid4(),
        session_id=uuid4(),
        purpose="integration testing",
        requested_scope="read",
    )
    provision(engine, ctx)
    return ctx


def _mark_shared(service, ctx, memory):
    return service.patch(
        ctx,
        memory.memory_id,
        MemoryPatch(owner_type="SHARED", expected_revision=memory.revision),
    )


def test_grant_exposes_only_shared_flagged_memories_to_the_grantee(
    service, ctx, grantee
):
    shared_memory = service.create(
        ctx, MemoryCreate(text="Project Cedar migrated to PostgreSQL")
    )
    shared_memory = _mark_shared(service, ctx, shared_memory)
    service.create(ctx, MemoryCreate(text="A private note about Cedar's budget"))

    sharing = SharingService(service)
    sharing.grant(ctx, ShareInput(grantee_user_id=grantee.user_id))

    with service.engine.begin() as db:
        visible = SQLMemoryRepository(db, grantee).shared_memories()

    assert [m.memory_id for m, _ in visible] == [shared_memory.memory_id]
    assert visible[0][1] == ctx.namespace_id


def test_revoking_a_grant_removes_visibility(service, ctx, grantee):
    memory = service.create(ctx, MemoryCreate(text="Project Cedar launch plan"))
    memory = _mark_shared(service, ctx, memory)
    sharing = SharingService(service)
    grant = sharing.grant(ctx, ShareInput(grantee_user_id=grantee.user_id))

    sharing.revoke(ctx, UUID(grant["share_id"]))

    with service.engine.begin() as db:
        visible = SQLMemoryRepository(db, grantee).shared_memories()
    assert visible == []


def test_private_memory_cannot_be_marked_shared(service, ctx):
    memory = service.create(
        ctx, MemoryCreate(text="Sensitive note", privacy_class="PRIVATE")
    )
    with pytest.raises(ValueError):
        _mark_shared(service, ctx, memory)


def test_correlate_surfaces_shared_memories_from_another_user(service, ctx, grantee):
    memory = service.create(
        ctx, MemoryCreate(text="Project Cedar uses PostgreSQL for storage")
    )
    _mark_shared(service, ctx, memory)
    SharingService(service).grant(ctx, ShareInput(grantee_user_id=grantee.user_id))

    result = CorrelationService(service).correlate(
        grantee, "What does Project Cedar use for storage?"
    )

    assert result["shared"]
    assert result["shared"][0]["namespace_id"] == str(ctx.namespace_id)
    assert "cedar" in {term for term in result["shared"][0]["shared_terms"]}


def test_outgoing_and_incoming_listings(service, ctx, grantee):
    sharing = SharingService(service)
    sharing.grant(ctx, ShareInput(grantee_user_id=grantee.user_id))

    outgoing = sharing.outgoing(ctx)
    incoming = sharing.incoming(grantee)

    assert len(outgoing) == 1
    assert outgoing[0]["grantee_user_id"] == str(grantee.user_id)
    assert len(incoming) == 1
    assert incoming[0]["namespace_id"] == str(ctx.namespace_id)


def test_cannot_share_a_namespace_with_yourself(service, ctx):
    with pytest.raises(ValueError):
        SharingService(service).grant(ctx, ShareInput(grantee_user_id=ctx.user_id))


def test_grantee_cannot_act_in_the_owners_namespace(service, ctx, grantee):
    foreign_ctx = grantee.model_copy(update={"namespace_id": ctx.namespace_id})
    with pytest.raises(AccessDenied):
        service.create(foreign_ctx, MemoryCreate(text="should be rejected"))
