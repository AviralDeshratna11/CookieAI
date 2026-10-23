"""Product facade over canonical memory and the existing durable supervisor."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import select, update

from database import procedure_tables as p
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.autonomy.contracts import TaskInput
from memory.autonomy.handoff import HandoffSpec, read_bounded, workspace_for, write_once
from memory.autonomy.service import TaskSupervisor
from memory.procedures.service import Procedure
from memory.procedures.skills import HandoffSkill, applicability
from memory.schemas import MemoryCreate, StrictModel, utcnow
from memory.security.auth import AccessDenied, Conflict, NotFound, require_scope


class SourceInput(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=8000)
    project_id: UUID | None = None
    disclosure: Literal["LOCAL_ONLY", "APPROVED_CLOUD"] = "LOCAL_ONLY"
    evidence_origin: Literal["REAL", "SYNTHETIC"] = "REAL"


class BriefInput(StrictModel):
    project: str = Field(min_length=1, max_length=100)
    source_ids: list[UUID] = Field(min_length=1, max_length=8)
    goal_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    mode: Literal["extractive", "model"] = "extractive"
    disclosure: Literal["LOCAL_ONLY", "APPROVED_CLOUD"] = "LOCAL_ONLY"
    repeat_seconds: int | None = Field(default=None, ge=60, le=2592000)
    max_runs: int = Field(default=1, ge=1, le=100)
    skill_id: UUID | None = None
    skill_revision: int | None = Field(default=None, ge=1)


class SkillConfirmation(StrictModel):
    expected_revision: int = Field(ge=1)
    explicitly_confirmed: Literal[True]
    contract: HandoffSkill


class Portal:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def add_source(self, ctx, body):
        TaskSupervisor(self.memory)._authorize(ctx)
        if not self.memory.settings.handoff_enabled:
            raise AccessDenied("Handoff workflow is disabled")
        if len(body.content.encode()) > 8192:
            raise ValueError("Source exceeds 8 KiB")
        source = self.memory.create(
            ctx,
            MemoryCreate(
                text=body.content,
                type="CONTEXT",
                source_type="DOCUMENT",
                tags=[
                    "handoff:source",
                    "title:" + body.title,
                    "evidence-origin:" + body.evidence_origin,
                ],
                disclosure=body.disclosure,
                allowed_agent_ids=[ctx.requesting_agent_id],
                allowed_project_ids=[body.project_id] if body.project_id else [],
            ),
        )
        root = workspace_for(self.memory, ctx)
        # Provisioned only by authenticated source registration; never model paths.
        root.mkdir(parents=True, exist_ok=True)
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            current = repo.get(source.memory_id)
            if current.status.value != "ACTIVE" or current.revision != source.revision:
                raise Conflict("Source changed before workspace publication")
            write_once(root, f"inputs/{source.memory_id}.txt", source.text.encode())
        return {
            "source_id": str(source.memory_id),
            "revision": source.revision,
            "sha256": hashlib.sha256(source.text.encode()).hexdigest(),
        }

    @require_scope("read")
    def sources(self, ctx):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            return [
                {
                    "source_id": str(item.memory_id),
                    "title": next(
                        (tag[6:] for tag in item.tags if tag.startswith("title:")),
                        "Project note",
                    ),
                    "disclosure": item.disclosure,
                    "revision": item.revision,
                    "status": item.status.value,
                }
                for item in repo.recent(limit=200)
                if "handoff:source" in item.tags
            ]

    @require_scope("read")
    def skills(self, ctx):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            rows = (
                db.execute(
                    select(p.procedures)
                    .join(t.memories, t.memories.c.id == p.procedures.c.id)
                    .where(t.memories.c.namespace_id == ctx.namespace_id)
                    .limit(200)
                )
                .mappings()
                .all()
            )
            visible = repo.get_many([row["id"] for row in rows], strict=False)
            return [
                {
                    "skill_id": str(row["id"]),
                    "revision": visible[row["id"]].revision,
                    "status": visible[row["id"]].status.value,
                    "procedure": row["payload"],
                }
                for row in rows
                if row["id"] in visible
            ]

    @require_scope("write")
    def confirm_skill(self, ctx, identity, body):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            memory = repo.get(identity)
            if (
                memory.revision != body.expected_revision
                or memory.status.value != "ACTIVE"
            ):
                raise Conflict("Skill evidence requires review")
            raw = db.execute(
                select(p.procedures.c.payload).where(p.procedures.c.id == identity)
            ).scalar_one_or_none()
            if raw is None:
                raise NotFound("Procedure not found")
            procedure = Procedure.model_validate(raw)
            if procedure.tools != ["cookieai_handoff"]:
                raise ValueError(
                    "Contract must specialize an observed handoff procedure"
                )
            procedure.skill_contract = body.contract
            repo.save(
                memory.model_copy(
                    update={
                        "revision": memory.revision + 1,
                        "updated_at": utcnow(),
                        "tags": [
                            tag
                            for tag in memory.tags
                            if not tag.startswith("skill-contract:")
                        ]
                        + ["skill-contract:" + body.contract.model_dump_json()],
                    }
                ),
                self.memory.vector(memory.canonical_text),
                "UPDATED",
            )
            db.execute(
                update(p.procedures)
                .where(p.procedures.c.id == identity)
                .values(payload=procedure.model_dump(mode="json"))
            )
        return {
            "skill_id": str(identity),
            "revision": memory.revision + 1,
            "validation": "USER_CONFIRMED",
        }

    def spec(self, ctx, body):
        snapshots = {}
        for identity in body.source_ids:
            source = self.memory.get(ctx, identity)
            if "handoff:source" not in source.tags or source.status.value != "ACTIVE":
                raise Conflict("Selected source is unavailable")
            snapshots[identity] = hashlib.sha256(source.text.encode()).hexdigest()
        return HandoffSpec(
            project=body.project,
            sources=snapshots,
            mode=body.mode,
            disclosure=body.disclosure,
        )

    @require_scope("read")
    def check(self, ctx, body):
        spec = self.spec(ctx, body)
        if not body.skill_id:
            return {
                "decision": "applicable",
                "reasons": ["Explicit task definition; no learned skill selected"],
            }
        return self.check_skill(ctx, body.skill_id, body.skill_revision, spec)

    def check_skill(self, ctx, identity, revision, spec):
        memory = self.memory.get(ctx, identity)
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.get(identity)
            raw = db.execute(
                select(p.procedures.c.payload).where(p.procedures.c.id == identity)
            ).scalar_one_or_none()
        if not raw:
            raise NotFound("Skill not found")
        contract = Procedure.model_validate(raw).skill_contract
        if not contract:
            return {
                "decision": "uncertain",
                "reasons": ["Procedure has no confirmed executable contract"],
            }
        return applicability(
            contract,
            spec,
            [self.memory.get(ctx, item).text for item in spec.sources],
            active=memory.status.value == "ACTIVE",
            revision_matches=memory.revision == revision,
        )

    @require_scope("write")
    def submit(self, ctx, body):
        check = self.check(ctx, body)
        if check["decision"] != "applicable":
            raise Conflict("Skill is not applicable: " + "; ".join(check["reasons"]))
        spec = self.spec(ctx, body)
        task = TaskInput(
            goal_id=body.goal_id,
            objective=f"Prepare a source-attributed handoff for {body.project}",
            idempotency_key=body.idempotency_key,
            allowed_tools=["cookieai_handoff"],
            steps=[
                {"tool": "cookieai_handoff", "arguments": spec.model_dump(mode="json")}
            ],
            verifier={"kind": "HANDOFF"},
            evidence_ids=body.source_ids,
            context_signature={
                "goal_type": "handoff",
                "domain": "project_management",
                "output_format": "markdown",
            },
            required_procedure_id=body.skill_id,
            procedure_revision=body.skill_revision,
            max_model_calls=1 if body.mode == "model" else 0,
            evidence_origin="SYNTHETIC"
            if any(
                "evidence-origin:SYNTHETIC" in self.memory.get(ctx, identity).tags
                for identity in body.source_ids
            )
            else "REAL",
            repeat_seconds=body.repeat_seconds,
            max_runs=body.max_runs,
            trigger="SCHEDULE" if body.repeat_seconds else "MANUAL",
            timeout_seconds=180,
        )
        return TaskSupervisor(self.memory).create(ctx, task)

    @require_scope("read")
    def artifact(self, ctx, task_id, run_id):
        task = TaskSupervisor(self.memory).get(ctx, task_id)
        run = next((run for run in task["runs"] if run["run_id"] == str(run_id)), None)
        if not run or not run["payload"].get("verification"):
            raise NotFound("Verified run artifact unavailable")
        raw = read_bounded(
            workspace_for(self.memory, ctx), f"outputs/{run_id}.json", 65536
        )
        expected = run["payload"]["verification"].get("evidence", {}).get("sha256")
        if not expected or hashlib.sha256(raw).hexdigest() != expected:
            raise Conflict("Artifact has changed since verification")
        return json.loads(raw)
