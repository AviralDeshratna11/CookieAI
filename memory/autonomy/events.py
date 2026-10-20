"""Event wakeups are data-driven; execution authority comes from approved tasks."""

from sqlalchemy import insert, select, update

from database import autonomy_tables as a
from database import tables as foundation
from database.repositories.memory import SQLMemoryRepository
from memory.autonomy.contracts import TaskInput
from memory.schemas import RequestContext, utcnow
from memory.security.auth import AccessDenied, NotFound


def wake_approved_tasks(supervisor, ctx, event_id):
    if not supervisor.memory.settings.autonomy_enabled:
        return {"activated": 0}
    with supervisor.memory.engine.begin() as db:
        repo = SQLMemoryRepository(db, ctx)
        repo.lock_namespace()
        event = (
            db.execute(
                select(foundation.outbox).where(
                    foundation.outbox.c.id == event_id,
                    foundation.outbox.c.namespace_id == ctx.namespace_id,
                )
            )
            .mappings()
            .first()
        )
        if not event or event["event_type"] not in {
            "MEMORY_CREATED",
            "MEMORY_UPDATED",
            "MEMORY_CORRECTED",
        }:
            return {"activated": 0}
        count = 0
        candidates = (
            db.execute(
                select(a.tasks)
                .where(
                    a.tasks.c.namespace_id == ctx.namespace_id,
                    a.tasks.c.status.in_(["QUEUED", "WAITING", "RUNNING"]),
                    a.tasks.c.payload["definition"]["trigger"].as_string() == "EVENT",
                )
                .order_by(a.tasks.c.created_at)
                .limit(500)
            )
            .mappings()
            .all()
        )
        for raw in candidates:
            row = dict(raw)
            body = TaskInput.model_validate(row["payload"]["definition"])
            approved = RequestContext.model_validate(row["execution_context"])
            if (
                approved.user_id != ctx.user_id
                or approved.namespace_id != ctx.namespace_id
                or approved.requesting_agent_id != row["agent_id"]
            ):
                continue
            from memory.autonomy.service import aware

            if aware(event["created_at"]) < aware(row["created_at"]):
                continue
            try:
                supervisor._authorize(approved)
                authorized = SQLMemoryRepository(db, approved)
                authorized.get(row["id"])
                source = authorized.get(event["object_id"])
            except (AccessDenied, NotFound):
                continue
            if (
                source.source_type == "DERIVED"
                or "autonomy:outcome" in source.tags
                or source.type.value == "GOAL"
            ):
                continue
            if not set(map(str.casefold, body.event_topics)).intersection(
                map(str.casefold, source.topics)
            ):
                continue
            if db.execute(
                select(a.events.c.event_id).where(
                    a.events.c.task_id == row["id"], a.events.c.event_id == event_id
                )
            ).first():
                continue
            db.execute(
                insert(a.events).values(
                    task_id=row["id"],
                    namespace_id=ctx.namespace_id,
                    event_id=event_id,
                    event_type=event["event_type"],
                    seen_at=utcnow(),
                )
            )
            payload = {
                **row["payload"],
                "pending_event": row["status"] == "RUNNING",
                "last_event_id": str(event_id),
            }
            if row["status"] == "RUNNING":
                db.execute(
                    update(a.tasks)
                    .where(a.tasks.c.id == row["id"])
                    .values(payload=payload)
                )
            else:
                due = max(body.start_at or utcnow(), utcnow())
                supervisor._transition(
                    db,
                    row,
                    "QUEUED",
                    "AuthorizedEvent",
                    payload=payload,
                    next_run_at=due,
                )
            count += 1
        return {"activated": count}
