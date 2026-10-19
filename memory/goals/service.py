from typing import Literal
from uuid import UUID

from sqlalchemy import insert, select, update

from database import context_tables as c
from database.repositories.memory import SQLMemoryRepository
from memory.schemas import Field, Memory, MemoryCreate, Score, StrictModel, utcnow
from memory.security.auth import Conflict, NotFound, require_scope


class GoalInput(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4000)
    status: Literal[
        "PLANNED", "ACTIVE", "BLOCKED", "PAUSED", "COMPLETED", "ABANDONED"
    ] = "ACTIVE"
    priority: Score = 0.5
    progress: Score = 0
    dependencies: list[UUID] = Field(default_factory=list, max_length=50)
    related_memories: list[UUID] = Field(default_factory=list, max_length=100)


class GoalPatch(StrictModel):
    status: (
        Literal["PLANNED", "ACTIVE", "BLOCKED", "PAUSED", "COMPLETED", "ABANDONED"]
        | None
    ) = None
    progress: Score | None = None
    expected_revision: int = Field(ge=1)


class GoalService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def create(self, ctx, body):
        from memory.provenance.policy import evidence_policy

        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            references = body.dependencies + body.related_memories
            evidence = [repo.get(item) for item in references]
            policy = evidence_policy(evidence)
            memory = self.memory._create(
                repo,
                MemoryCreate(
                    text=body.title + ". " + body.description,
                    type="GOAL",
                    epistemic_type="USER_STATED",
                    importance=body.priority,
                    **policy,
                ),
            )
            payload = body.model_dump(mode="json")
            payload.update(
                goal_id=str(memory.memory_id),
                owner_id=str(ctx.user_id),
                created_at=utcnow().isoformat(),
                revision=1,
            )
            if not connection.execute(
                select(c.goals.c.id).where(c.goals.c.id == memory.memory_id)
            ).first():
                connection.execute(
                    insert(c.goals).values(id=memory.memory_id, payload=payload)
                )
                for parent in body.dependencies:
                    if not connection.execute(
                        select(c.goals.c.id).where(c.goals.c.id == parent)
                    ).first():
                        raise ValueError("goal dependency must identify a goal")
                    connection.execute(
                        insert(c.goal_relations).values(
                            parent_id=parent, child_id=memory.memory_id
                        )
                    )
            return payload

    @require_scope("read")
    def list(self, ctx):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            result = []
            for row in connection.execute(select(c.goals)):
                try:
                    repo.get(row.id)
                except NotFound:
                    continue
                result.append(row.payload)
            return result

    @require_scope("write")
    def patch(self, ctx, goal_id, body):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            memory = repo.get(goal_id)
            row = connection.execute(
                select(c.goals.c.payload).where(c.goals.c.id == goal_id)
            ).first()
            if not row:
                raise NotFound("goal not found")
            payload = dict(row.payload)
            if payload["revision"] != body.expected_revision:
                raise Conflict("goal revision changed")
            for key in ("status", "progress"):
                if getattr(body, key) is not None:
                    payload[key] = getattr(body, key)
            payload["revision"] += 1
            payload["updated_at"] = utcnow().isoformat()
            values = memory.model_dump()
            values.update(revision=memory.revision + 1, updated_at=utcnow())
            repo.save(
                Memory.model_validate(values),
                self.memory.vector(memory.canonical_text),
                "UPDATED",
            )
            connection.execute(
                update(c.goals).where(c.goals.c.id == goal_id).values(payload=payload)
            )
            return payload
