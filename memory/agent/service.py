"""Durable assistant turns: recall, generation, ingestion, and attributed outcomes."""

import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4, uuid5

from sqlalchemy import insert, select, update

from database import cognitive_tables as c
from database import operations_tables as o
from database import source_tables as sources
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.agent.capabilities import assistant_system_prompt, capabilities
from memory.context.budget import TokenCounter, check_prompt, serialize
from memory.context.transfer import ContextRequest, ContextTransferService
from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.schemas import (
    Field,
    Memory,
    MessageInput,
    RememberRequest,
    StrictModel,
    utcnow,
)
from memory.security.auth import AccessDenied, Conflict, NotFound, require_scope
from memory.security.identifiers import job_key, opaque
from models.providers import Provider
from workers.queue import JobQueue


class TurnInput(StrictModel):
    message: str = Field(min_length=1, max_length=16000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    mode: str = Field(default="infer", pattern="^(infer|raw)$")
    retain: bool = True
    context_signature: dict = Field(default_factory=dict)
    token_budget: int = Field(default=8000, ge=1000, le=32000)
    backend: Literal["assistant", "hermes"] = "assistant"


class TurnFeedback(StrictModel):
    feedback_id: UUID
    helpful_memory_ids: list[UUID] = Field(default_factory=list, max_length=100)
    episode: EpisodeInput | None = None


class AgentService:
    def __init__(self, memory, generator=None, *, backend_factory=None):
        self.memory = memory
        generator = generator or getattr(memory, "assistant_generator", None)
        settings = memory.settings
        if generator is None and settings.assistant_provider_base_url:
            from pydantic import SecretStr

            # An explicit route never inherits another provider's credential.
            settings = settings.model_copy(
                update={
                    "provider_base_url": settings.assistant_provider_base_url,
                    "provider_api_key": settings.assistant_provider_api_key
                    or SecretStr(""),
                    "provider_enable_thinking": None,
                }
            )
        self.generator = generator or Provider(settings)
        self.backend_factory = backend_factory

    def _execution_guard(self, ctx, identity, refs):
        from memory.agent.hermes import HermesBackend

        HermesBackend.authorize(self.memory.settings, ctx, True)
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            if self._row(repo, identity)["status"] != "EXECUTING":
                raise AccessDenied("execution is no longer active")
            self._validate_refs(repo, refs)

    def _record_execution_observation(self, ctx, identity, refs, observation):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            if row["status"] != "EXECUTING":
                raise AccessDenied("execution is no longer active")
            self._validate_refs(repo, refs)
            execution = dict((row["response"] or {}).get("execution", {}))
            observations = list(execution.get("observations", []))
            sequence = observation["sequence"]
            if sequence == len(observations):
                observations.append(observation)
            elif (
                sequence == len(observations) - 1
                and observations[sequence]["event_id"] == observation["event_id"]
            ):
                observations[sequence] = observation
            else:
                raise Conflict("Execution observation sequence changed")
            execution.update(
                backend="hermes",
                run_id=str(identity),
                status="UNKNOWN",
                task_success=None,
                observations=observations,
            )
            db.execute(
                update(c.turns)
                .where(c.turns.c.id == identity)
                .values(response={"execution": execution}, updated_at=utcnow())
            )

    def generate(self, body, context):
        payload = {
            "model": self.memory.settings.assistant_model
            or self.memory.settings.extraction_model,
            "temperature": 0,
            "max_tokens": self.memory.settings.assistant_output_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": assistant_system_prompt(
                        self.memory.settings, body.backend, body.retain
                    ),
                },
                {
                    "role": "user",
                    "content": serialize(
                        {
                            "current_user_request": body.message,
                            "untrusted_memory_context": context,
                        }
                    ),
                },
            ],
        }
        if (
            self.memory.settings.assistant_completion_limit_parameter
            == "max_completion_tokens"
        ):
            payload["max_completion_tokens"] = payload.pop("max_tokens")
        if self.memory.settings.assistant_reasoning_effort is not None:
            payload["reasoning_effort"] = (
                self.memory.settings.assistant_reasoning_effort
            )
        check_prompt(
            payload["messages"],
            TokenCounter(self.memory.settings.context_tokenizer_file),
            self.memory.settings.assistant_prompt_tokens,
            self.memory.settings.assistant_output_tokens,
            self.memory.settings.assistant_template_reserve_tokens,
        )
        response = self.generator.post(
            "/chat/completions",
            payload,
        )
        answer = response["choices"][0]["message"]["content"]
        if response["choices"][0].get("finish_reason") in {"length", "content_filter"}:
            raise ValueError("assistant response is incomplete or refused")
        if isinstance(answer, str) and ("<think>" in answer or "</think>" in answer):
            raise ValueError("assistant response contains an invalid final segment")
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 16000:
            raise ValueError("assistant response must be nonempty bounded text")
        return answer

    def _row(self, repo, identity):
        row = (
            repo.db.execute(
                select(c.turns).where(
                    c.turns.c.id == identity,
                    c.turns.c.namespace_id == repo.ctx.namespace_id,
                    c.turns.c.agent_id == repo.ctx.requesting_agent_id,
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise NotFound()
        return row

    def _refs(self, repo, package):
        ids = set()
        keys = {
            "memory_id",
            "episode_id",
            "experience_id",
            "procedure_id",
            "insight_id",
            "goal_id",
            "prospective_id",
        }

        def visit(item):
            if isinstance(item, dict):
                for key, value in item.items():
                    if key in keys:
                        try:
                            ids.add(UUID(str(value)))
                        except ValueError:
                            pass
                    visit(value)
            elif isinstance(item, list):
                for value in item:
                    visit(value)

        visit(package)
        result = {}
        pending = set(ids)
        while pending:
            if len(result) + len(pending) > 500:
                raise ValueError("context provenance exceeds bounded verification")
            memories = repo.get_many(pending)
            pending = set()
            for identity, memory in memories.items():
                result[str(identity)] = memory.revision
                pending.update(memory.provenance_ids)
            pending = {identity for identity in pending if str(identity) not in result}
        return result

    def _validate_refs(self, repo, refs, require_versions=True):
        stale = False
        memories = repo.get_many([UUID(identity) for identity in refs])
        for identity, revision in refs.items():
            memory = memories[UUID(identity)]
            if not repo.valid_at(memory) or memory.status.value not in {
                "ACTIVE",
                "DISPUTED",
            }:
                stale = True
            stale = stale or memory.revision != revision
        if stale and require_versions:
            raise Conflict("Context evidence changed; retry using a fresh context")
        return stale

    @require_scope("write")
    def submit(self, ctx, body):
        if body.backend == "hermes":
            from memory.agent.hermes import HermesBackend

            HermesBackend.authorize(self.memory.settings, ctx, body.retain)
        if not body.retain:
            context = ContextTransferService(self.memory).build(
                ctx,
                ContextRequest(
                    query=body.message,
                    token_budget=body.token_budget,
                    context_signature=body.context_signature,
                ),
            )
            return {
                "status": "COMPLETED",
                "answer": self.generate(body, context),
                "retained": False,
            }
        payload = body.model_dump(mode="json")
        if body.backend == "assistant":
            # Preserve request hashes of turns submitted before backend selection.
            payload.pop("backend")
        digest = hashlib.sha256(serialize(payload).encode()).hexdigest()
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            repo.session()
            previous = (
                db.execute(
                    select(c.turns).where(
                        c.turns.c.namespace_id == ctx.namespace_id,
                        c.turns.c.agent_id == ctx.requesting_agent_id,
                        c.turns.c.idempotency_key == opaque(body.idempotency_key),
                    )
                )
                .mappings()
                .first()
            )
            if previous:
                if (
                    previous["request_hash"] != digest
                    or previous["session_id"] != ctx.session_id
                ):
                    raise Conflict(
                        "Turn identity was reused with different input or session"
                    )
                return {
                    "turn_id": str(previous["id"]),
                    "status": previous["status"],
                    "replayed": True,
                }
            identity = uuid4()
            db.execute(
                insert(c.turns).values(
                    id=identity,
                    namespace_id=ctx.namespace_id,
                    agent_id=ctx.requesting_agent_id,
                    session_id=ctx.session_id,
                    idempotency_key=opaque(body.idempotency_key),
                    request_hash=digest,
                    status="PENDING",
                    payload=payload,
                    response=None,
                    context_refs={},
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            job = JobQueue(self.memory.engine).enqueue(
                ctx,
                "memory.agent_turn",
                {"turn_id": str(identity)},
                "turn:" + str(identity),
                priority=0,
                connection=db,
            )
            return {"turn_id": str(identity), "job_id": str(job), "status": "PENDING"}

    @require_scope("read")
    def get(self, ctx, identity):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            row = self._row(repo, identity)
            if row["status"] == "CANCELLED":
                return {"turn_id": str(identity), "status": "CANCELLED", "answer": None}
            stale = self._validate_refs(repo, row["context_refs"], False)
            job = (
                repo.db.execute(
                    select(
                        o.jobs.c.id,
                        o.jobs.c.status,
                        o.jobs.c.last_error,
                        o.jobs.c.available_at,
                    ).where(
                        o.jobs.c.namespace_id == ctx.namespace_id,
                        o.jobs.c.idempotency_key
                        == job_key(ctx.namespace_id, f"turn:{identity}"),
                    )
                )
                .mappings()
                .first()
            )
            return {
                "turn_id": str(identity),
                "status": row["status"],
                **(row["response"] or {}),
                "context_requires_revalidation": stale,
                "job_id": str(job["id"]) if job else None,
                "job_status": job["status"] if job else None,
                "failure_class": job["last_error"] if job else None,
            }

    @require_scope("write")
    def process(self, ctx, identity):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            if row["status"] == "CANCELLED":
                raise AccessDenied("turn was canceled")
            if row["status"] == "COMPLETED":
                return row["response"]
            body = TurnInput.model_validate(row["payload"])
            response = row["response"]
            refs = row["context_refs"]
            if body.backend == "hermes" and row["status"] == "EXECUTING":
                # A crashed process may have performed an action. A retry must
                # never launch another execution under the same turn identity.
                response = {
                    "answer": "The previous execution outcome is unknown. It was not replayed.",
                    "execution": {
                        "backend": "hermes",
                        "run_id": str(identity),
                        "status": "UNKNOWN",
                        "task_success": None,
                        "observations": (row["response"] or {})
                        .get("execution", {})
                        .get("observations", []),
                    },
                    "context_memory_ids": list(refs),
                    "memory_ids": [],
                    "feedback": {},
                    "retained": True,
                }
                db.execute(
                    update(c.turns)
                    .where(c.turns.c.id == identity)
                    .values(response=response, status="RESPONDED", updated_at=utcnow())
                )
            if response and self._validate_refs(repo, refs, False):
                if body.backend == "hermes":
                    raise Conflict(
                        "Execution evidence changed; execution cannot be replayed"
                    )
                response, refs = None, {}
                db.execute(
                    update(c.turns)
                    .where(c.turns.c.id == identity)
                    .values(
                        response=None,
                        context_refs={},
                        status="PENDING",
                        updated_at=utcnow(),
                    )
                )
        # No namespace write transaction is held during context retrieval/model calls.
        if response is None:
            package = ContextTransferService(self.memory).build(
                ctx,
                ContextRequest(
                    query=body.message,
                    token_budget=body.token_budget,
                    context_signature=body.context_signature,
                ),
            )
            with self.memory.engine.begin() as db:
                repo = SQLMemoryRepository(db, ctx)
                repo.lock_namespace()
                refs = self._refs(repo, package)
                snapshot_start = datetime.fromisoformat(
                    package["source_snapshot_started_at"]
                )
                if any(
                    memory.updated_at > snapshot_start
                    for memory in repo.get_many([UUID(key) for key in refs]).values()
                ):
                    raise Conflict(
                        "Context changed during assembly; retry with a fresh snapshot"
                    )
                db.execute(
                    update(c.turns)
                    .where(c.turns.c.id == identity)
                    .values(context_refs=refs, updated_at=utcnow())
                )
                if ctx.execution_job_id:
                    dependencies = db.execute(
                        select(o.jobs.c.dependencies).where(
                            o.jobs.c.id == ctx.execution_job_id
                        )
                    ).scalar_one()
                    db.execute(
                        update(o.jobs)
                        .where(o.jobs.c.id == ctx.execution_job_id)
                        .values(
                            dependencies={
                                **dependencies,
                                "memory_ids": sorted(
                                    set(dependencies.get("memory_ids", [])) | set(refs)
                                ),
                            }
                        )
                    )
            execution = None
            if body.backend == "hermes":
                from memory.agent.hermes import HermesBackend

                if len(refs) > 88:
                    raise ValueError(
                        "Hermes pilot supports at most 88 context dependencies plus 12 new memories"
                    )
                workspace = (
                    self.memory.settings.hermes_workspace
                    / str(ctx.namespace_id)
                    / str(ctx.requesting_agent_id)
                )
                backend = (self.backend_factory or HermesBackend)(
                    self.memory.settings,
                    workspace=workspace,
                    guard=lambda: self._execution_guard(ctx, identity, refs),
                    on_observation=lambda observation: (
                        self._record_execution_observation(
                            ctx, identity, refs, observation
                        )
                    ),
                )
                backend.authorize(self.memory.settings, ctx, body.retain)
                with self.memory.engine.begin() as db:
                    repo = SQLMemoryRepository(db, ctx)
                    repo.lock_namespace()
                    current = self._row(repo, identity)
                    if current["status"] != "PENDING":
                        raise Conflict("Execution has already been claimed")
                    self._validate_refs(repo, refs)
                    claimed = db.execute(
                        update(c.turns)
                        .where(c.turns.c.id == identity, c.turns.c.status == "PENDING")
                        .values(status="EXECUTING", updated_at=utcnow())
                    )
                    if claimed.rowcount != 1:
                        raise Conflict("Execution has already been claimed")
                execution = backend.run(identity, body.message, package).model_dump(
                    mode="json"
                )
                answer = execution["answer"]
            else:
                answer = self.generate(body, package)
            response = {
                "answer": answer,
                "pipeline": {
                    "capabilities": capabilities(self.memory.settings, body.backend),
                    "session_id": str(ctx.session_id),
                    "model": self.memory.settings.assistant_model
                    or self.memory.settings.extraction_model,
                    "context_generated_at": package.get("generated_at"),
                    "context_budget": package.get("context_budget", {}),
                    "related_sessions": package.get("related_sessions", []),
                    "correlation_method": "shared terms and entities; heuristic, not causality",
                    "stages": [
                        "authorized_retrieval",
                        "session_correlation",
                        "bounded_context",
                        "generation",
                    ],
                },
                "context_memory_ids": list(refs),
                "memory_ids": [],
                "feedback": {},
                "retained": True,
            }
            if execution:
                response["execution"] = execution
            with self.memory.engine.begin() as db:
                repo = SQLMemoryRepository(db, ctx)
                repo.lock_namespace()
                self._validate_refs(repo, refs)
                db.execute(
                    update(c.turns)
                    .where(c.turns.c.id == identity)
                    .values(response=response, status="RESPONDED", updated_at=utcnow())
                )
        else:
            with self.memory.engine.begin() as db:
                repo = SQLMemoryRepository(db, ctx)
                repo.lock_namespace()
                self._validate_refs(repo, refs)
        message = MessageInput(
            role="user", content=body.message, message_id=uuid5(identity, "user")
        )
        memories = self.memory.remember(
            ctx,
            RememberRequest(
                messages=[message],
                mode=body.mode,
                idempotency_key="turn:" + str(identity),
            ),
        )
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            current = self._row(repo, identity)
            if current["status"] == "CANCELLED":
                raise AccessDenied("turn was canceled")
            if current["status"] == "COMPLETED":
                return current["response"]
            self._validate_refs(repo, refs)
            execution = response.get("execution", {})
            observations = [
                item
                for item in execution.get("observations", [])
                if item.get("success") is not None
            ]
            if observations:
                episode = EpisodeService(self.memory)._save(
                    repo,
                    EpisodeInput(
                        event_id=uuid5(identity, "execution-observations"),
                        title="Hermes bounded tool execution",
                        trigger="Explicit Hermes turn",
                        goal="Record actual tool attempts; task outcome remains unverified",
                        context={
                            **{
                                key: value
                                for key, value in body.context_signature.items()
                                if key
                                in {
                                    "goal_type",
                                    "domain",
                                    "error_category",
                                    "environment",
                                    "workflow_stage",
                                }
                                and isinstance(value, str)
                                and 0 < len(value) <= 200
                            },
                            "backend": "hermes",
                            "run_id": str(identity),
                        },
                        attempts=[
                            ToolAttempt(
                                observation_id=UUID(item["event_id"]),
                                sequence=item["sequence"],
                                tool=item["tool"],
                                intent="Execute permitted pilot operation",
                                action=item["tool"],
                                parameters={},
                                result="Tool returned successfully"
                                if item["success"]
                                else "Tool failed",
                                success=item["success"],
                                error=item.get("error_class"),
                            )
                            for item in observations
                        ],
                        linked_memory_ids=list(
                            {UUID(key) for key in refs}
                            | {item.memory_id for item in memories}
                        ),
                        outcome="unknown",
                        start_time=datetime.fromisoformat(
                            observations[0]["started_at"]
                        ),
                        end_time=datetime.fromisoformat(observations[-1]["ended_at"]),
                    ),
                )
                response = {**response, "execution_episode_id": str(episode.episode_id)}
                JobQueue(self.memory.engine).enqueue(
                    ctx,
                    "memory.experience",
                    {"episode_id": str(episode.episode_id)},
                    "execution-experience:" + str(identity),
                    connection=db,
                )
            # Assistant output is retained as source/history, never promoted to an
            # independent factual observation by automatic extraction.
            assistant = MessageInput(
                role="assistant",
                content=response["answer"],
                message_id=uuid5(identity, "assistant"),
            )
            db.execute(
                insert(sources.sources).values(
                    id=assistant.message_id,
                    namespace_id=ctx.namespace_id,
                    session_id=ctx.session_id,
                    created_at=utcnow(),
                    payload={
                        "kind": "ASSISTANT_OUTPUT",
                        "message": assistant.model_dump(mode="json"),
                        "independent_evidence": False,
                    },
                )
            )
            repo.append_messages([assistant], self.memory.policy(repo).rolling_messages)
            response = {**response, "memory_ids": [str(m.memory_id) for m in memories]}
            db.execute(
                update(c.turns)
                .where(c.turns.c.id == identity)
                .values(response=response, status="COMPLETED", updated_at=utcnow())
            )
            JobQueue(self.memory.engine).enqueue(
                ctx,
                "memory.summarize",
                {},
                "turn-summary:" + str(identity),
                connection=db,
            )
        return response

    @require_scope("write")
    def cancel(self, ctx, identity):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            if row["status"] == "COMPLETED":
                raise Conflict("Completed turns cannot be canceled")
            db.execute(
                update(c.turns)
                .where(c.turns.c.id == identity)
                .values(
                    status="CANCELLED",
                    payload={},
                    response=None,
                    context_refs={},
                    updated_at=utcnow(),
                )
            )
            db.execute(
                update(o.jobs)
                .where(
                    o.jobs.c.namespace_id == ctx.namespace_id,
                    o.jobs.c.idempotency_key
                    == job_key(ctx.namespace_id, f"turn:{identity}"),
                )
                .values(
                    status="CANCELLED",
                    payload={},
                    dependencies={},
                    lease_token=None,
                    lease_until=None,
                )
            )
            return {
                "turn_id": str(identity),
                "status": "CANCELLED",
                "external_effects_reversed": False,
            }

    @require_scope("write")
    def feedback(self, ctx, identity, body):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            row = self._row(repo, identity)
            if row["status"] != "COMPLETED":
                raise Conflict("Feedback requires a completed turn")
            self._validate_refs(repo, row["context_refs"], False)
            response = dict(row["response"])
            receipts = dict(response.get("feedback", {}))
            key = str(body.feedback_id)
            digest = hashlib.sha256(
                serialize(body.model_dump(mode="json", exclude_unset=True)).encode()
            ).hexdigest()
            if key in receipts:
                if receipts[key]["request_hash"] != digest:
                    raise Conflict("Feedback identity was reused with different input")
                return receipts[key]
            if len(receipts) >= 100:
                raise Conflict("This turn has reached its feedback receipt limit")
            if not set(map(str, body.helpful_memory_ids)).issubset(row["context_refs"]):
                raise ValueError("Feedback can refer only to supplied context")
            for memory_id in set(body.helpful_memory_ids):
                memory = repo.get(memory_id)
                vector = db.execute(
                    select(t.embeddings.c.vector).where(
                        t.embeddings.c.memory_id == memory_id
                    )
                ).scalar_one()
                values = memory.model_dump()
                values.update(
                    successful_use_count=memory.successful_use_count + 1,
                    memory_strength=min(1, memory.memory_strength + 0.05),
                    revision=memory.revision + 1,
                    updated_at=utcnow(),
                )
                repo.save(Memory.model_validate(values), vector, "REINFORCED")
            episode = None
            if body.episode:
                episode = EpisodeService(self.memory)._save(
                    repo,
                    body.episode.model_copy(
                        update={
                            "event_id": uuid5(identity, key),
                            "linked_memory_ids": [],
                        }
                    ),
                )
            receipt = {
                "request_hash": digest,
                "helpful_memory_ids": list(map(str, body.helpful_memory_ids)),
                "episode_id": str(episode.episode_id) if episode else None,
            }
            receipts[key] = receipt
            response["feedback"] = receipts
            db.execute(
                update(c.turns)
                .where(c.turns.c.id == identity)
                .values(response=response, updated_at=utcnow())
            )
            if episode:
                JobQueue(self.memory.engine).enqueue(
                    ctx,
                    "memory.experience",
                    {"episode_id": str(episode.episode_id)},
                    "outcome:" + key,
                    connection=db,
                )
                JobQueue(self.memory.engine).enqueue(
                    ctx, "memory.reflect", {}, "outcome-reflect:" + key, connection=db
                )
            return receipt
