import pytest

from memory.schemas import MemoryCreate, MessageInput, RememberRequest
from memory.security.auth import AccessDenied
from workers.queue import JobQueue


def test_deletion_cancels_claimed_jobs_before_they_can_restore_private_input(
    service, ctx
):
    memory = service.create(ctx, MemoryCreate(text="Private source"))
    queue = JobQueue(service.engine)
    request = RememberRequest(
        mode="raw",
        idempotency_key="pending-raw",
        messages=[MessageInput(role="user", content="Private source")],
    )
    queue.enqueue(
        ctx, "memory.extract", request.model_dump(mode="json"), "pending-raw-job"
    )
    claimed = queue.claim()
    service.delete(ctx, memory.memory_id)
    executing = ctx.model_copy(
        update={
            "execution_job_id": claimed["id"],
            "execution_lease_token": claimed["lease_token"],
        }
    )
    with pytest.raises(AccessDenied, match="canceled"):
        service.remember(executing, request)
    assert service.export(ctx)["memories"] == []
