from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import insert, select, update

from database import context_tables as c
from database import dynamics_tables as d
from database.repositories.memory import SQLMemoryRepository
from memory.schemas import Field, MemoryCreate, StrictModel, utcnow
from memory.security.auth import NotFound, require_scope


class ProspectiveInput(StrictModel):
    trigger_type: Literal["TIME", "DATE", "ENTITY", "EVENT", "CONTEXT", "GOAL_STATE"]
    trigger: dict
    action_or_memory: str = Field(min_length=1, max_length=4000)
    expires_at: datetime | None = None


class LoopInput(StrictModel):
    description: str = Field(min_length=1, max_length=4000)
    linked_goal: UUID | None = None


class ProspectiveService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def create(self, ctx, body):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            if body.expires_at:
                MemoryCreate.aware_time(body.expires_at)
            if body.trigger_type in {"TIME", "DATE"}:
                MemoryCreate.aware_time(datetime.fromisoformat(body.trigger["at"]))
            elif body.trigger_type == "GOAL_STATE":
                repo.get(UUID(body.trigger["goal_id"]))
            elif (
                not isinstance(body.trigger.get("value"), str)
                or not body.trigger["value"].strip()
            ):
                raise ValueError("trigger requires a nonblank value")
            memory = self.memory._create(
                repo,
                MemoryCreate(
                    text="Prospective reminder: " + body.action_or_memory,
                    type="TASK",
                    expires_at=body.expires_at,
                ),
            )
            payload = body.model_dump(mode="json")
            payload.update(prospective_id=str(memory.memory_id), status="WAITING")
            if not connection.execute(
                select(d.prospective.c.id).where(d.prospective.c.id == memory.memory_id)
            ).first():
                connection.execute(
                    insert(d.prospective).values(id=memory.memory_id, payload=payload)
                )
            return payload

    @require_scope("write")
    def activate(self, ctx, context, now=None):
        now = MemoryCreate.aware_time(now or utcnow())
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            result = []
            for row in connection.execute(select(d.prospective)):
                try:
                    repo.get(row.id)
                except NotFound:
                    continue
                payload = dict(row.payload)
                if payload["status"] != "WAITING":
                    continue
                if (
                    payload["expires_at"]
                    and datetime.fromisoformat(payload["expires_at"]) <= now
                ):
                    continue
                trigger = payload["trigger"]
                kind = payload["trigger_type"]
                if kind in {"TIME", "DATE"}:
                    matched = datetime.fromisoformat(trigger["at"]) <= now
                elif kind == "GOAL_STATE":
                    goal = connection.execute(
                        select(c.goals.c.payload).where(
                            c.goals.c.id == UUID(trigger["goal_id"])
                        )
                    ).scalar()
                    matched = bool(goal and goal["status"] == trigger.get("status"))
                else:
                    matched = (
                        trigger["value"].casefold()
                        in str(context.get(kind.casefold(), "")).casefold()
                    )
                if matched:
                    payload["status"] = "ACTIVATED"
                    connection.execute(
                        update(d.prospective)
                        .where(d.prospective.c.id == row.id)
                        .values(payload=payload)
                    )
                    result.append(payload)
            return result

    @require_scope("write")
    def open_loop(self, ctx, body):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            if body.linked_goal:
                repo.get(body.linked_goal)
            memory = self.memory._create(
                repo, MemoryCreate(text=body.description, type="TASK")
            )
            payload = {
                "loop_id": str(memory.memory_id),
                **body.model_dump(mode="json"),
                "status": "OPEN",
                "originating_session": str(ctx.session_id),
                "opened_at": utcnow().isoformat(),
            }
            if not connection.execute(
                select(d.open_loops.c.id).where(d.open_loops.c.id == memory.memory_id)
            ).first():
                connection.execute(
                    insert(d.open_loops).values(id=memory.memory_id, payload=payload)
                )
            return payload
