from sqlalchemy import func, select

from database import graph_tables as g
from database import operations_tables as o
from memory.schemas import MemoryCreate
from workers.queue import JobQueue


def test_export_and_namespace_deletion_remove_queued_raw_and_graph_entities(
    service, ctx, engine
):
    service.create(
        ctx, MemoryCreate(text="Private raw source", entities=["SecretProject"])
    )
    JobQueue(engine).enqueue(
        ctx,
        "memory.extract",
        {"messages": [{"content": "Private raw source"}]},
        "pending-private",
    )
    assert len(service.export(ctx)["memories"]) == 1
    result = service.delete_namespace_memory(ctx)
    assert result["deleted"] == 1
    assert service.export(ctx)["memories"] == []
    with engine.connect() as db:
        assert db.execute(select(func.count()).select_from(o.jobs)).scalar() == 0
        assert db.execute(select(func.count()).select_from(g.nodes)).scalar() == 0
