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


def from_insight(memory_service, repo, insight, finding, feature):
    """An inferred opportunity inherits its finding's evidence and permissions."""
    import json

    from memory.provenance.policy import evidence_policy

    description = json.loads(feature)
    tool = description.get("tool") or description.get("context")
    if not tool or finding["status"] != "ACTIVE":
        return None
    reminder = memory_service._create(
        repo,
        MemoryCreate(
            text="When discussing "
            + tool
            + ", review the conditional association: "
            + finding["statement"],
            type="TASK",
            epistemic_type="INFERRED",
            source_type="DERIVED",
            provenance_ids=[insight.memory_id],
            truth_confidence=insight.truth_confidence,
            **evidence_policy([insight]),
        ),
    )
    existing = repo.db.execute(
        select(d.prospective.c.id).where(d.prospective.c.id == reminder.memory_id)
    ).first()
    if not existing:
        repo.db.execute(
            insert(d.prospective).values(
                id=reminder.memory_id,
                payload={
                    "prospective_id": str(reminder.memory_id),
                    "trigger_type": "CONTEXT",
                    "trigger": {"value": tool},
                    "action_or_memory": reminder.text,
                    "expires_at": None,
                    "status": "WAITING",
                    "origin": "INFERRED_OPPORTUNITY",
                    "epistemic_type": "INFERRED",
                    "truth_confidence": insight.truth_confidence,
                    "provenance_ids": [str(insight.memory_id)],
                    "requires_contextual_review": True,
                },
            )
        )
    return reminder.memory_id


class LoopInput(StrictModel):
    description: str = Field(min_length=1, max_length=4000)
    linked_goal: UUID | None = None


class ProspectiveFeedback(StrictModel):
    status: Literal["ACKNOWLEDGED", "DISMISSED", "SNOOZED", "WAITING"]
    snooze_until: datetime | None = None
    helpful: bool | None = None


class ProspectiveService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("read")
    def list(self, ctx):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            result = []
            for row in db.execute(select(d.prospective)):
                try:
                    canonical = repo.get(row.id)
                except NotFound:
                    continue
                if canonical.status.value != "ACTIVE" or not repo.valid_at(canonical):
                    continue
                result.append(row.payload)
            return result

    @require_scope("read")
    def matching(self, ctx, context, now=None):
        """Preview relevant opportunities without mutating state on a read request."""
        now = now or utcnow()
        result = []
        for payload in self.list(ctx):
            if payload["status"] not in {"WAITING", "ACTIVATED", "SNOOZED"}:
                continue
            if (
                payload.get("expires_at")
                and datetime.fromisoformat(payload["expires_at"]) <= now
            ):
                continue
            if (
                payload.get("snooze_until")
                and datetime.fromisoformat(payload["snooze_until"]) > now
            ):
                continue
            kind, trigger = payload["trigger_type"], payload["trigger"]
            if kind in {"TIME", "DATE"}:
                matched = datetime.fromisoformat(trigger["at"]) <= now
            elif kind == "GOAL_STATE":
                from memory.goals.service import GoalService

                matched = any(
                    item["goal_id"] == trigger["goal_id"]
                    and item["status"] == trigger.get("status")
                    for item in GoalService(self.memory).list(ctx)
                )
            else:
                matched = (
                    trigger["value"].casefold()
                    in str(context.get(kind.casefold(), "")).casefold()
                )
            if matched:
                result.append(
                    {
                        **payload,
                        "match_reason": f"Matched recorded {kind} condition",
                        "read_only_preview": True,
                    }
                )
        return result

    @require_scope("write")
    def feedback(self, ctx, prospective_id, body):
        if body.status == "SNOOZED":
            if (
                not body.snooze_until
                or MemoryCreate.aware_time(body.snooze_until) <= utcnow()
            ):
                raise ValueError("snooze requires a future aware timestamp")
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            repo.get(prospective_id)
            payload = db.execute(
                select(d.prospective.c.payload).where(
                    d.prospective.c.id == prospective_id
                )
            ).scalar()
            if payload is None:
                raise NotFound()
            payload = {
                **payload,
                **body.model_dump(mode="json"),
                "last_feedback_at": utcnow().isoformat(),
            }
            db.execute(
                update(d.prospective)
                .where(d.prospective.c.id == prospective_id)
                .values(payload=payload)
            )
            return payload

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
            existing = connection.execute(
                select(d.prospective.c.payload).where(
                    d.prospective.c.id == memory.memory_id
                )
            ).scalar()
            if existing:
                return existing
            else:
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
                if payload["status"] not in {"WAITING", "SNOOZED"}:
                    continue
                if (
                    payload.get("snooze_until")
                    and datetime.fromisoformat(payload["snooze_until"]) > now
                ):
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
                    payload["last_activated_at"] = now.isoformat()
                    payload["match_reason"] = f"Matched recorded {kind} trigger"
                    payload["activation_count"] = payload.get("activation_count", 0) + 1
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
