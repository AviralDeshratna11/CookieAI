"""Durable bounded task supervisor on the existing SQL queue and memory ACLs.

The first task family is explicitly read-only. Success is a deterministic check,
not the executor's narrative. A lost run is never automatically relaunched.
"""

import copy
import hashlib
import time
from datetime import timedelta, timezone
from uuid import UUID, uuid4, uuid5

from sqlalchemy import and_, exists, func, insert, or_, select, update

from database import autonomy_tables as a
from database import context_tables as goals
from database import operations_tables as operations
from database.repositories.memory import SQLMemoryRepository
from memory.agent.hermes_tools import execute_tool
from memory.agent.service import AgentService
from memory.autonomy.budgets import charge, stop_on_budget
from memory.autonomy.contracts import TaskInput
from memory.autonomy.verifiers import verify
from memory.context.budget import serialize
from memory.context.transfer import ContextRequest, ContextTransferService
from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.experiences.service import structural_similarity
from memory.provenance.policy import evidence_policy
from memory.schemas import MemoryCreate, RequestContext, utcnow
from memory.security.auth import AccessDenied, Conflict, NotFound, require_scope
from memory.security.identifiers import opaque
from workers.queue import JobQueue

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "EXHAUSTED", "UNCERTAIN"}


def aware(value):
    return (
        value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
    )


class TaskSupervisor:
    def __init__(self, memory):
        self.memory = memory

    def _authorize(self, ctx):
        if (
            not self.memory.settings.autonomy_enabled
            or str(ctx.requesting_agent_id)
            not in self.memory.settings.autonomy_allowed_agents
        ):
            raise AccessDenied("Autonomous execution is not enabled for this agent")

    def _row(self, repo, identity, *, owner=True):
        repo.get(identity)
        row = (
            repo.db.execute(
                select(a.tasks).where(
                    a.tasks.c.id == identity,
                    a.tasks.c.namespace_id == repo.ctx.namespace_id,
                )
            )
            .mappings()
            .first()
        )
        if not row or (owner and row["agent_id"] != repo.ctx.requesting_agent_id):
            raise NotFound("task not found")
        return dict(row)

    def _transition(self, db, row, status, reason, *, payload=None, next_run_at=None):
        payload = copy.deepcopy(row["payload"] if payload is None else payload)
        history = payload.get("history", [])
        history.append(
            {
                "from": row["status"],
                "to": status,
                "reason": reason,
                "at": utcnow().isoformat(),
            }
        )
        payload["history"] = history[-50:]
        payload["reason"] = reason
        changes = dict(
            status=status,
            payload=payload,
            revision=row["revision"] + 1,
            updated_at=utcnow(),
            next_run_at=next_run_at,
        )
        result = db.execute(
            update(a.tasks)
            .where(a.tasks.c.id == row["id"], a.tasks.c.revision == row["revision"])
            .values(**changes)
        )
        if result.rowcount != 1:
            raise Conflict("Task state changed")
        return {**row, **changes}

    @require_scope("write")
    def create(self, ctx, body: TaskInput):
        self._authorize(ctx)
        if body.backend == "hermes":
            from memory.agent.hermes import HermesBackend

            HermesBackend.authorize(self.memory.settings, ctx, True)
        digest = hashlib.sha256(
            serialize(body.model_dump(mode="json")).encode()
        ).hexdigest()
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            previous = (
                db.execute(
                    select(a.tasks).where(
                        a.tasks.c.namespace_id == ctx.namespace_id,
                        a.tasks.c.agent_id == ctx.requesting_agent_id,
                        a.tasks.c.idempotency_key == opaque(body.idempotency_key),
                    )
                )
                .mappings()
                .first()
            )
            if previous:
                repo.get(previous["id"])
                if previous["request_hash"] != digest:
                    raise Conflict(
                        "Task identity was reused with a different definition"
                    )
                return {
                    "task_id": str(previous["id"]),
                    "status": previous["status"],
                    "replayed": True,
                }
            if body.trigger == "EVENT":
                subscribed = db.execute(
                    select(func.count())
                    .select_from(a.tasks)
                    .where(
                        a.tasks.c.namespace_id == ctx.namespace_id,
                        a.tasks.c.status.not_in(TERMINAL),
                        a.tasks.c.payload["definition"]["trigger"].as_string()
                        == "EVENT",
                    )
                ).scalar_one()
                if subscribed >= 500:
                    raise ValueError("Namespace event-subscription limit reached")
            repo.session()
            refs = set(body.evidence_ids + body.depends_on + [body.goal_id])
            if body.parent_task_id:
                parent = self._row(repo, body.parent_task_id)
                if parent["goal_id"] != body.goal_id:
                    raise ValueError("child task must have the same goal")
                refs.add(body.parent_task_id)
            for dependency in body.depends_on:
                self._row(repo, dependency)
            if body.required_procedure_id:
                refs.add(body.required_procedure_id)
                if (
                    repo.get(body.required_procedure_id).revision
                    != body.procedure_revision
                ):
                    raise Conflict("Procedure revision changed before approval")
            if not db.execute(
                select(goals.goals.c.id).where(goals.goals.c.id == body.goal_id)
            ).first():
                raise ValueError("task must identify an existing authorized goal")
            evidence = [repo.get(item) for item in refs]
            identity = uuid4()
            policy = evidence_policy(evidence)
            policy["allowed_agent_ids"] = [ctx.requesting_agent_id]
            if policy["privacy_class"] in {"PUBLIC", "NORMAL"}:
                policy["privacy_class"] = "PRIVATE"
            memory = self.memory._create(
                repo,
                MemoryCreate(
                    text=f"Approved task {identity}: {body.objective}",
                    type="GOAL",
                    source_type="DERIVED",
                    epistemic_type="USER_STATED",
                    provenance_ids=sorted(refs, key=str),
                    **policy,
                ),
            )
            trusted = ctx.model_copy(
                update={
                    "execution_job_id": None,
                    "execution_lease_token": None,
                    "requested_scope": "write",
                }
            )
            payload = {
                "definition": body.model_dump(mode="json"),
                "runs_used": 0,
                "evaluations_used": 0,
                "approved_revisions": {
                    str(item.memory_id): item.revision for item in evidence
                },
                "history": [],
            }
            db.execute(
                insert(a.tasks).values(
                    id=memory.memory_id,
                    namespace_id=ctx.namespace_id,
                    agent_id=ctx.requesting_agent_id,
                    goal_id=body.goal_id,
                    idempotency_key=opaque(body.idempotency_key),
                    request_hash=digest,
                    status="WAITING" if body.trigger == "EVENT" else "QUEUED",
                    revision=1,
                    payload=payload,
                    execution_context=trusted.model_dump(mode="json"),
                    next_run_at=None
                    if body.trigger == "EVENT"
                    else body.start_at or utcnow(),
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            return {
                "task_id": str(memory.memory_id),
                "status": "WAITING" if body.trigger == "EVENT" else "QUEUED",
                "revision": 1,
            }

    @require_scope("read")
    def get(self, ctx, identity):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            row = self._row(repo, identity)
            runs = []
            for run in db.execute(
                select(a.runs)
                .where(a.runs.c.task_id == identity)
                .order_by(a.runs.c.sequence.desc())
                .limit(10)
            ).mappings():
                payload = run["payload"]
                refs = payload.get("context_refs", {})
                visible = repo.get_many([UUID(key) for key in refs], strict=False)
                if len(visible) != len(refs):
                    payload = {"reason": "EvidenceUnavailable"}
                runs.append(
                    {
                        "run_id": str(run["id"]),
                        "status": run["status"],
                        "sequence": run["sequence"],
                        "payload": payload,
                    }
                )
            return {
                "task_id": str(identity),
                "goal_id": str(row["goal_id"]),
                "status": row["status"],
                "revision": row["revision"],
                "next_run_at": row["next_run_at"].isoformat()
                if row["next_run_at"]
                else None,
                "state": row["payload"],
                "runs": runs,
            }

    @require_scope("read")
    def list(self, ctx, *, after=None, limit=20):
        if not 1 <= limit <= 100:
            raise ValueError("task page limit outside bounds")
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            query = select(a.tasks.c.id, a.tasks.c.status, a.tasks.c.revision).where(
                a.tasks.c.namespace_id == ctx.namespace_id,
                a.tasks.c.agent_id == ctx.requesting_agent_id,
            )
            if after:
                query = query.where(a.tasks.c.id > after)
            rows = db.execute(query.order_by(a.tasks.c.id).limit(limit)).all()
            visible = repo.get_many([row.id for row in rows], strict=False)
            return {
                "items": [
                    {
                        "task_id": str(row.id),
                        "status": row.status,
                        "revision": row.revision,
                    }
                    for row in rows
                    if row.id in visible
                ],
                "next_cursor": str(rows[-1].id) if len(rows) == limit else None,
            }

    @require_scope("write")
    def tick(self, ctx):
        """Scheduler reads server-stored approval contexts, never model identities."""
        if not self.memory.settings.autonomy_enabled:
            return {"scheduled": 0}
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            rows = (
                db.execute(
                    select(a.tasks)
                    .where(
                        a.tasks.c.namespace_id == ctx.namespace_id,
                        or_(
                            and_(
                                a.tasks.c.status.in_(["QUEUED", "WAITING"]),
                                a.tasks.c.next_run_at <= utcnow(),
                            ),
                            and_(
                                a.tasks.c.status == "RUNNING",
                                exists(
                                    select(a.runs.c.id).where(
                                        a.runs.c.task_id == a.tasks.c.id,
                                        a.runs.c.status == "RUNNING",
                                        a.runs.c.lease_until <= utcnow(),
                                    )
                                ),
                            ),
                        ),
                    )
                    .order_by(a.tasks.c.next_run_at, a.tasks.c.created_at)
                    .limit(self.memory.settings.autonomy_batch_size)
                )
                .mappings()
                .all()
            )
            count = 0
            for raw in rows:
                row = dict(raw)
                try:
                    approved = RequestContext.model_validate(row["execution_context"])
                    if (
                        approved.namespace_id != ctx.namespace_id
                        or approved.user_id != ctx.user_id
                        or approved.requesting_agent_id != row["agent_id"]
                    ):
                        raise AccessDenied("invalid task execution context")
                    self._authorize(approved)
                    SQLMemoryRepository(db, approved).get(row["id"])
                except (AccessDenied, NotFound, ValueError):
                    # A revoked approval must not occupy every scheduling batch
                    # indefinitely and starve later authorized work.
                    self._transition(
                        db, row, "PAUSED", "ExecutionAuthorizationUnavailable"
                    )
                    continue
                body = TaskInput.model_validate(row["payload"]["definition"])
                key = f"task:{row['id']}:{row['revision']}" + (
                    ":reconcile" if row["status"] == "RUNNING" else ""
                )
                job = JobQueue(self.memory.engine).enqueue(
                    approved,
                    "autonomy.run",
                    {"task_id": str(row["id"])},
                    key,
                    priority=body.priority,
                    connection=db,
                )
                # The queue enforces availability and retries; the task keeps its
                # due date until a worker actually evaluates it.
                payload = {**row["payload"], "scheduled_job_id": str(job)}
                db.execute(
                    update(a.tasks)
                    .where(a.tasks.c.id == row["id"])
                    .values(payload=payload)
                )
                count += 1
            return {"scheduled": count}

    @require_scope("write")
    def wake(self, ctx, event_id):
        from memory.autonomy.events import wake_approved_tasks

        return wake_approved_tasks(self, ctx, event_id)

    @require_scope("read")
    def status(self, ctx):
        """Bounded, object-authorized progress and usage; never expose content."""
        from collections import Counter

        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            rows = (
                db.execute(
                    select(a.tasks)
                    .where(
                        a.tasks.c.namespace_id == ctx.namespace_id,
                        a.tasks.c.agent_id == ctx.requesting_agent_id,
                    )
                    .order_by(a.tasks.c.updated_at.desc(), a.tasks.c.id)
                    .limit(501)
                )
                .mappings()
                .all()
            )
            truncated = len(rows) > 500
            rows = rows[:500]
            visible = repo.get_many([row["id"] for row in rows], strict=False)
            rows = [row for row in rows if row["id"] in visible]
            counts = Counter(row["status"] for row in rows)
            verdicts = Counter(
                row["payload"].get("last_verdict")
                for row in rows
                if row["payload"].get("last_verdict")
            )
            pending = [
                aware(row["next_run_at"])
                for row in rows
                if row["status"] in {"QUEUED", "WAITING"} and row["next_run_at"]
            ]
            completed = [
                aware(row["updated_at"]) for row in rows if row["status"] == "COMPLETED"
            ]
            usage = (
                db.execute(
                    select(a.usage).where(
                        a.usage.c.namespace_id == ctx.namespace_id,
                        a.usage.c.agent_id == ctx.requesting_agent_id,
                        a.usage.c.day == utcnow().date().isoformat(),
                    )
                )
                .mappings()
                .first()
            )
            return {
                "enabled_for_agent": self.memory.settings.autonomy_enabled
                and str(ctx.requesting_agent_id)
                in self.memory.settings.autonomy_allowed_agents,
                "window": "500 most recently updated owned tasks, filtered by current object access",
                "truncated": truncated,
                "task_counts": dict(counts),
                "latest_verdict_counts": dict(verdicts),
                "oldest_due_age_seconds": max(
                    0, (utcnow() - min(pending)).total_seconds()
                )
                if pending
                else None,
                "last_completed_task_at": max(completed).isoformat()
                if completed
                else None,
                "daily_usage": {
                    "day": utcnow().date().isoformat(),
                    "tool_calls": usage["tool_calls"] if usage else 0,
                    "model_calls": usage["model_calls"] if usage else 0,
                },
                "daily_limits": {
                    "tool_calls": self.memory.settings.autonomy_daily_tool_calls,
                    "model_calls": self.memory.settings.autonomy_daily_model_calls,
                },
                "heartbeat_is_completion_evidence": False,
            }

    @require_scope("write")
    def control(self, ctx, identity, body):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            if row["revision"] != body.expected_revision:
                raise Conflict("Task revision changed")
            if row["status"] in TERMINAL:
                raise Conflict("Terminal tasks require a new explicitly approved task")
            if body.action == "RESUME":
                self._authorize(ctx)
                if row["status"] != "PAUSED":
                    raise Conflict("Only paused tasks can resume")
                self._transition(db, row, "QUEUED", "Resumed", next_run_at=utcnow())
            else:
                status = "PAUSED" if body.action == "PAUSE" else "CANCELLED"
                self._transition(db, row, status, body.action)
                db.execute(
                    update(a.runs)
                    .where(a.runs.c.task_id == identity, a.runs.c.status == "RUNNING")
                    .values(status="UNCERTAIN", finished_at=utcnow())
                )
                job_id = row["payload"].get("scheduled_job_id")
                if job_id:
                    db.execute(
                        update(operations.jobs)
                        .where(
                            operations.jobs.c.id == UUID(job_id),
                            operations.jobs.c.namespace_id == ctx.namespace_id,
                        )
                        .values(
                            status="CANCELLED",
                            payload={},
                            lease_token=None,
                            lease_until=None,
                        )
                    )
            return {
                "task_id": str(identity),
                "status": "QUEUED" if body.action == "RESUME" else status,
                "revision": row["revision"] + 1,
                "external_effects_reversed": False,
            }

    def _guard(self, ctx, identity, run_id, token, refs, deadline):
        self._authorize(ctx)
        if deadline and utcnow() >= deadline:
            raise TimeoutError("task deadline or execution budget reached")
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            run = (
                db.execute(select(a.runs).where(a.runs.c.id == run_id)).mappings().one()
            )
            if (
                row["status"] != "RUNNING"
                or run["status"] != "RUNNING"
                or run["lease_token"] != token
                or aware(run["lease_until"]) <= utcnow()
            ):
                raise AccessDenied("Task execution is no longer active")
            task_memory = repo.get(identity)
            if (
                task_memory.status.value != "ACTIVE"
                or task_memory.revision != run["payload"]["task_memory_revision"]
            ):
                raise Conflict("Task approval changed")
            AgentService(self.memory)._validate_refs(repo, refs)
            goal = db.execute(
                select(goals.goals.c.payload).where(goals.goals.c.id == row["goal_id"])
            ).scalar_one()
            if goal["status"] != "ACTIVE":
                raise AccessDenied("Goal is no longer active")

    def _journal(self, ctx, identity, run_id, token, refs, deadline, observation):
        self._guard(ctx, identity, run_id, token, refs, deadline)
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            run = (
                db.execute(select(a.runs).where(a.runs.c.id == run_id)).mappings().one()
            )
            if (
                row["status"] != "RUNNING"
                or run["status"] != "RUNNING"
                or run["lease_token"] != token
                or aware(run["lease_until"]) <= utcnow()
            ):
                raise AccessDenied("Run was fenced")
            AgentService(self.memory)._validate_refs(repo, refs)
            payload = copy.deepcopy(run["payload"])
            steps = payload["observations"]
            index = observation["sequence"]
            if index == len(steps):
                if observation["phase"] == "STARTED":
                    charge(
                        db,
                        ctx,
                        self.memory.settings,
                        UUID(observation["event_id"]),
                        "tool_calls",
                    )
                steps.append(observation)
            elif (
                index == len(steps) - 1
                and steps[index]["event_id"] == observation["event_id"]
            ):
                steps[index] = observation
            else:
                raise Conflict("Observation sequence changed")
            db.execute(
                update(a.runs)
                .where(a.runs.c.id == run_id, a.runs.c.lease_token == token)
                .values(payload=payload)
            )

    def _meter_model(self, ctx, identity, run_id, token, refs, deadline, sequence):
        self._guard(ctx, identity, run_id, token, refs, deadline)
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            if self._row(repo, identity)["status"] != "RUNNING":
                raise AccessDenied("Task was fenced")
            charge(
                db,
                ctx,
                self.memory.settings,
                uuid5(run_id, f"model:{sequence}"),
                "model_calls",
            )

    def _stop_for_budget(self, ctx, identity):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            if row["status"] != "RUNNING":
                return {"status": row["status"]}
            db.execute(
                update(a.runs)
                .where(a.runs.c.task_id == identity, a.runs.c.status == "RUNNING")
                .values(status="EXHAUSTED", finished_at=utcnow())
            )
            self._transition(db, row, "EXHAUSTED", "DailyExecutionBudget")
            return {
                "task_id": str(identity),
                "status": "EXHAUSTED",
                "reason": "DailyExecutionBudget",
            }

    @require_scope("write")
    @stop_on_budget
    def process(self, ctx, identity):
        self._authorize(ctx)
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            if row["status"] in TERMINAL or row["status"] == "PAUSED":
                return {"status": row["status"]}
            body = TaskInput.model_validate(row["payload"]["definition"])
            if row["status"] == "RUNNING":
                run = (
                    db.execute(
                        select(a.runs)
                        .where(a.runs.c.task_id == identity)
                        .order_by(a.runs.c.sequence.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one()
                )
                if aware(run["lease_until"]) > utcnow():
                    return {"status": "RUNNING"}
                db.execute(
                    update(a.runs)
                    .where(a.runs.c.id == run["id"])
                    .values(status="UNCERTAIN", finished_at=utcnow())
                )
                self._transition(db, row, "UNCERTAIN", "LostExecutionNotReplayed")
                return {"status": "UNCERTAIN"}
            if row["next_run_at"] is None or aware(row["next_run_at"]) > utcnow():
                return {"status": "WAITING"}
            payload = copy.deepcopy(row["payload"])
            if (
                payload["runs_used"] >= body.max_runs
                or payload["evaluations_used"] >= body.max_evaluations
                or (body.deadline and body.deadline <= utcnow())
            ):
                self._transition(db, row, "EXHAUSTED", "BudgetOrDeadline")
                return {"status": "EXHAUSTED"}
            payload["evaluations_used"] += 1
            goal_state = db.execute(
                select(goals.goals.c.payload).where(goals.goals.c.id == body.goal_id)
            ).scalar_one()
            if goal_state["status"] in {"COMPLETED", "ABANDONED"}:
                self._transition(
                    db, row, "CANCELLED", "ParentGoalClosed", payload=payload
                )
                return {"status": "CANCELLED", "reason": "ParentGoalClosed"}
            if (
                db.execute(
                    select(goals.goals.c.payload).where(
                        goals.goals.c.id == body.goal_id
                    )
                ).scalar_one()["status"]
                != "ACTIVE"
            ):
                self._transition(
                    db,
                    row,
                    "WAITING",
                    "GoalNotActive",
                    payload=payload,
                    next_run_at=utcnow() + timedelta(seconds=body.retry_seconds),
                )
                return {"status": "WAITING"}
            dependencies = [self._row(repo, dep) for dep in body.depends_on]
            if any(dep["status"] != "COMPLETED" for dep in dependencies):
                self._transition(
                    db,
                    row,
                    "WAITING",
                    "DependencyPending",
                    payload=payload,
                    next_run_at=utcnow() + timedelta(seconds=body.retry_seconds),
                )
                return {"status": "WAITING"}
            try:
                AgentService(self.memory)._validate_refs(
                    repo, payload["approved_revisions"]
                )
                if repo.get(identity).status.value != "ACTIVE":
                    raise Conflict("Task approval is no longer active")
            except (Conflict, NotFound):
                self._transition(
                    db, row, "WAITING", "ApprovalRequiresReview", payload=payload
                )
                return {"status": "WAITING", "reason": "ApprovalRequiresReview"}
            if body.required_procedure_id:
                from database import procedure_tables
                from memory.procedures.service import Procedure

                # Use the same authorized transaction. A similarity ranking is
                # insufficient to waive a known environment/precondition change.
                procedure_memory = repo.get(body.required_procedure_id)
                procedure_payload = db.execute(
                    select(procedure_tables.procedures.c.payload).where(
                        procedure_tables.procedures.c.id == body.required_procedure_id
                    )
                ).scalar_one_or_none()
                if not procedure_payload:
                    raise NotFound("procedure not found")
                procedure = Procedure.model_validate(procedure_payload)
                signature = {
                    **body.context_signature,
                    "tools": sorted(body.allowed_tools),
                }
                conditions_changed = any(
                    value
                    and key not in {"tools", "entities", "outcome"}
                    and str(signature.get(key, "")).strip().casefold()
                    != str(value).strip().casefold()
                    for key, value in procedure.context_signature.items()
                )
                if (
                    procedure_memory.status.value != "ACTIVE"
                    or conditions_changed
                    or structural_similarity(procedure.context_signature, signature)
                    < 0.65
                ):
                    self._transition(
                        db,
                        row,
                        "WAITING",
                        "ProcedureNotApplicable",
                        payload=payload,
                        next_run_at=utcnow() + timedelta(seconds=body.retry_seconds),
                    )
                    return {"status": "WAITING"}
            # Save the evaluation without changing the immutable approval definition.
            db.execute(
                update(a.tasks).where(a.tasks.c.id == identity).values(payload=payload)
            )
        retrieval_started = time.monotonic()
        package = ContextTransferService(self.memory).build(
            ctx,
            ContextRequest(
                query=body.objective, context_signature=body.context_signature
            ),
        )
        retrieval_latency_ms = (time.monotonic() - retrieval_started) * 1000
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            if row["status"] not in {"QUEUED", "WAITING"}:
                raise Conflict("Task state changed during context assembly")
            refs = {
                **row["payload"]["approved_revisions"],
                **AgentService(self.memory)._refs(repo, package),
            }
            if len(refs) > 60:
                raise ValueError("Task context has too many evidence dependencies")
            AgentService(self.memory)._validate_refs(repo, refs)
            started = __import__("datetime").datetime.fromisoformat(
                package["source_snapshot_started_at"]
            )
            if any(
                item.updated_at > started
                for item in repo.get_many([UUID(key) for key in refs]).values()
            ):
                raise Conflict("Task evidence changed during context assembly")
            payload = copy.deepcopy(row["payload"])
            payload["runs_used"] += 1
            sequence = payload["runs_used"]
            run_id, token = uuid5(identity, f"run:{sequence}"), uuid4()
            deadline = (
                min(utcnow() + timedelta(seconds=body.timeout_seconds), body.deadline)
                if body.deadline
                else utcnow() + timedelta(seconds=body.timeout_seconds)
            )
            self._transition(db, row, "RUNNING", "ExecutionClaimed", payload=payload)
            db.execute(
                insert(a.runs).values(
                    id=run_id,
                    task_id=identity,
                    namespace_id=ctx.namespace_id,
                    sequence=sequence,
                    status="RUNNING",
                    lease_token=token,
                    lease_until=deadline + timedelta(seconds=30),
                    started_at=utcnow(),
                    payload={
                        "context_refs": refs,
                        "observations": [],
                        "evidence_origin": body.evidence_origin,
                        "retrieval_latency_ms": retrieval_latency_ms,
                        "task_memory_revision": repo.get(identity).revision,
                    },
                )
            )
            if ctx.execution_job_id:
                dependencies = db.execute(
                    select(operations.jobs.c.dependencies).where(
                        operations.jobs.c.id == ctx.execution_job_id
                    )
                ).scalar_one()
                db.execute(
                    update(operations.jobs)
                    .where(operations.jobs.c.id == ctx.execution_job_id)
                    .values(
                        dependencies={
                            **dependencies,
                            "memory_ids": sorted(
                                set(dependencies.get("memory_ids", []))
                                | set(refs)
                                | {str(identity)}
                            ),
                        }
                    )
                )

        def guard():
            return self._guard(ctx, identity, run_id, token, refs, deadline)

        def journal(observation):
            return self._journal(
                ctx, identity, run_id, token, refs, deadline, observation
            )

        workspace = (
            self.memory.settings.hermes_workspace
            / str(ctx.namespace_id)
            / str(ctx.requesting_agent_id)
        )
        receipts = []
        for criterion in body.preconditions:
            check = verify(criterion, workspace, [], guard=guard)
            if check.verdict != "PASS":
                return self._finish(
                    ctx,
                    identity,
                    run_id,
                    token,
                    refs,
                    body,
                    receipts,
                    check,
                    reason="PreconditionNotMet",
                )
        if body.backend == "deterministic":
            for index, step in enumerate(body.steps):
                guard()
                observation = {
                    "event_id": str(uuid5(run_id, f"attempt:{index}")),
                    "sequence": index,
                    "tool": step.tool,
                    "phase": "STARTED",
                    "success": None,
                    "started_at": utcnow().isoformat(),
                    "ended_at": None,
                    "arguments": step.arguments,
                    "result": {},
                }
                journal(observation)
                began = time.monotonic()
                try:
                    output = execute_tool(step.tool, step.arguments, workspace)
                    observation.update(
                        success=True,
                        result={"value": output["value"]}
                        if "value" in output
                        else {
                            "sha256": hashlib.sha256(
                                output["text"].encode()
                            ).hexdigest(),
                            "bytes": len(output["text"].encode()),
                        },
                    )
                except Exception as error:
                    observation.update(success=False, error_class=type(error).__name__)
                observation.update(
                    phase="FINISHED",
                    ended_at=utcnow().isoformat(),
                    latency_ms=(time.monotonic() - began) * 1000,
                )
                guard()
                journal(observation)
                receipts.append(observation)
                if not observation["success"] and step.on_failure == "STOP":
                    break
        else:
            from memory.agent.hermes import HermesBackend

            settings = self.memory.settings.model_copy(
                update={
                    "hermes_max_iterations": min(
                        body.max_model_calls, self.memory.settings.hermes_max_iterations
                    ),
                    "hermes_timeout_seconds": max(
                        5,
                        min(
                            body.timeout_seconds,
                            self.memory.settings.hermes_timeout_seconds,
                        ),
                    ),
                }
            )

            def capture(observation, output):
                if (
                    observation["tool"] == "cookieai_calculate"
                    and observation["success"]
                ):
                    observation = {**observation, "result": {"value": output["value"]}}
                else:
                    observation = {**observation, "result": {}}
                journal(observation)
                receipts.append(observation)

            def bounded_journal(observation):
                if observation["sequence"] >= body.max_tool_calls:
                    raise ValueError("Task tool budget reached")
                journal(observation)

            result = HermesBackend(
                settings,
                guard=guard,
                workspace=workspace,
                allowed_tools=body.allowed_tools,
                on_observation=bounded_journal,
                on_tool_result=capture,
                retain_tool_parameters=True,
                model_call_limit=body.max_model_calls,
                on_model_request=lambda sequence: self._meter_model(
                    ctx, identity, run_id, token, refs, deadline, sequence
                ),
            ).run(run_id, body.objective, package)
            if result.status != "COMPLETED":
                from memory.autonomy.contracts import Verification

                check = Verification(
                    verdict="INCONCLUSIVE",
                    criterion=body.verifier.kind,
                    checked_at=utcnow(),
                    limitations=["Executor did not complete"],
                )
                return self._finish(
                    ctx,
                    identity,
                    run_id,
                    token,
                    refs,
                    body,
                    receipts,
                    check,
                    reason="ExecutionIncomplete",
                )
        check = verify(body.verifier, workspace, receipts, guard=guard)
        return self._finish(ctx, identity, run_id, token, refs, body, receipts, check)

    def _finish(
        self, ctx, identity, run_id, token, refs, body, receipts, check, *, reason=None
    ):
        # Finalization repeats authorization and revision checks inside the commit.
        self._authorize(ctx)
        # An execution gets an attributable session, rather than pretending all
        # future observations happened in the original approval conversation.
        # Distinct sessions remain a proxy, not proof of independent evidence.
        ctx = ctx.model_copy(
            update={"session_id": uuid5(run_id, "observation-session")}
        )
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            repo.session()
            row = self._row(repo, identity)
            run = (
                db.execute(select(a.runs).where(a.runs.c.id == run_id)).mappings().one()
            )
            if (
                row["status"] != "RUNNING"
                or run["status"] != "RUNNING"
                or run["lease_token"] != token
            ):
                raise AccessDenied("Task result was fenced")
            if aware(run["lease_until"]) <= utcnow():
                raise AccessDenied("Task result lease expired")
            AgentService(self.memory)._validate_refs(repo, refs)
            current = repo.get(identity)
            if (
                current.status.value != "ACTIVE"
                or current.revision != run["payload"]["task_memory_revision"]
            ):
                raise Conflict("Task approval changed before finalization")
            payload = copy.deepcopy(run["payload"])
            payload["verification"] = check.model_dump(mode="json")
            payload["memory_utility"] = {
                "supplied_memory_revisions": refs,
                "influenced_action_ids": None,
                "attribution_limit": "Retrieved context was supplied; causal influence on model decisions is not established",
                "verified_verdict": check.verdict,
                "retrieval_latency_ms": payload.get("retrieval_latency_ms"),
                "observed_tool_calls": len(receipts),
                "truth_confidence_changed": False,
            }
            provenance = [
                repo.get(key) for key in {identity} | {UUID(key) for key in refs}
            ]
            policy = evidence_policy(provenance)
            outcome = self.memory._create(
                repo,
                MemoryCreate(
                    text=serialize(
                        {
                            "run_id": str(run_id),
                            "verification": check.model_dump(mode="json"),
                            "evidence_origin": body.evidence_origin,
                        }
                    ),
                    type="OBSERVATION",
                    source_type="TOOL",
                    source_id=uuid5(run_id, "verification"),
                    epistemic_type="OBSERVED",
                    provenance_ids=[item.memory_id for item in provenance],
                    tags=[
                        "autonomy:outcome",
                        "evidence-origin:" + body.evidence_origin,
                    ],
                    **policy,
                ),
            )
            payload["verification_memory_id"] = str(outcome.memory_id)
            if receipts:
                episode = EpisodeService(self.memory)._save(
                    repo,
                    EpisodeInput(
                        event_id=run_id,
                        title="Verified autonomous task execution",
                        trigger=body.trigger,
                        goal=body.objective[:1000],
                        context={
                            **body.context_signature,
                            "evidence_origin": body.evidence_origin,
                        },
                        evidence_origin=body.evidence_origin,
                        attempts=[
                            ToolAttempt(
                                observation_id=UUID(item["event_id"]),
                                sequence=item["sequence"],
                                tool=item["tool"],
                                intent="Approved task operation",
                                action=item["tool"],
                                parameters=item.get("arguments", {}),
                                result="Observed tool success"
                                if item["success"]
                                else "Observed tool failure",
                                success=bool(item["success"]),
                                error=item.get("error_class"),
                                latency_ms=item.get("latency_ms", 0),
                            )
                            for item in receipts
                        ],
                        linked_memory_ids=[outcome.memory_id],
                        outcome="success"
                        if check.verdict == "PASS"
                        else "failure"
                        if check.verdict == "FAIL"
                        else "unknown",
                    ),
                )
                payload["episode_id"] = str(episode.episode_id)
                if body.evidence_origin == "REAL":
                    JobQueue(self.memory.engine).enqueue(
                        ctx,
                        "memory.experience",
                        {"episode_id": str(episode.episode_id)},
                        "task-learning:" + str(run_id),
                        connection=db,
                    )
            db.execute(
                update(a.runs)
                .where(a.runs.c.id == run_id, a.runs.c.lease_token == token)
                .values(
                    status="VERIFIED"
                    if check.verdict == "PASS"
                    else "FAILED"
                    if check.verdict == "FAIL"
                    else "INCONCLUSIVE",
                    payload=payload,
                    finished_at=utcnow(),
                )
            )
            more = row["payload"]["runs_used"] < body.max_runs
            repeat = (
                check.verdict != "PASS"
                or body.repeat_seconds is not None
                or body.trigger == "EVENT"
            )
            status = (
                "WAITING"
                if more and repeat
                else "COMPLETED"
                if check.verdict == "PASS"
                else "FAILED"
                if check.verdict == "FAIL"
                else "UNCERTAIN"
            )
            task_payload = {
                **row["payload"],
                "last_run_id": str(run_id),
                "last_verdict": check.verdict,
            }
            interval = (
                body.repeat_seconds if check.verdict == "PASS" else body.retry_seconds
            )
            pending = bool(task_payload.pop("pending_event", False))
            next_run_at = (
                utcnow() + timedelta(seconds=interval or body.retry_seconds)
                if status == "WAITING"
                else None
            )
            if body.trigger == "EVENT" and check.verdict == "PASS" and not pending:
                next_run_at = None
            if check.verdict == "PASS" and body.complete_goal_on_success:
                parent = repo.get(body.goal_id)
                goal_payload = dict(
                    db.execute(
                        select(goals.goals.c.payload).where(
                            goals.goals.c.id == body.goal_id
                        )
                    ).scalar_one()
                )
                goal_payload.update(
                    status="COMPLETED",
                    progress=1,
                    revision=goal_payload["revision"] + 1,
                    updated_at=utcnow().isoformat(),
                )
                repo.save(
                    parent.model_copy(
                        update={"revision": parent.revision + 1, "updated_at": utcnow()}
                    ),
                    self.memory.vector(parent.canonical_text),
                    "UPDATED",
                )
                db.execute(
                    update(goals.goals)
                    .where(goals.goals.c.id == body.goal_id)
                    .values(payload=goal_payload)
                )
                status, next_run_at = "COMPLETED", None
            self._transition(
                db,
                row,
                status,
                reason or check.verdict,
                payload=task_payload,
                next_run_at=next_run_at,
            )
            return {
                "task_id": str(identity),
                "run_id": str(run_id),
                "status": status,
                "verification": check.model_dump(mode="json"),
            }
