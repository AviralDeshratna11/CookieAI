from sqlalchemy import func, select

from database import source_tables, tables
from memory.schemas import MessageInput, RememberRequest


def test_durable_sources_survive_rolling_context_but_not_forgetting(
    service, ctx, engine
):
    first = None
    for index in range(12):
        items = service.remember(
            ctx,
            RememberRequest(
                mode="raw",
                idempotency_key=f"source-{index}",
                messages=[
                    MessageInput(role="user", content=f"Durable evidence {index}")
                ],
            ),
        )
        if first is None:
            first = items[0]
    with engine.connect() as db:
        assert (
            db.execute(select(func.count()).select_from(tables.messages)).scalar() == 10
        )
        assert (
            db.execute(select(func.count()).select_from(source_tables.sources)).scalar()
            == 12
        )
        assert (
            db.execute(
                select(source_tables.sources.c.payload).where(
                    source_tables.sources.c.id == first.source_id
                )
            ).scalar()["content"]
            == "Durable evidence 0"
        )
    service.delete(ctx, first.memory_id)
    with engine.connect() as db:
        assert (
            db.execute(
                select(source_tables.sources.c.payload).where(
                    source_tables.sources.c.id == first.source_id
                )
            ).first()
            is None
        )
