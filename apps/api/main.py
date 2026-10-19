"""App factory. Authentication is fail-closed; startup does not mutate the database."""

import logging
import time
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError

from database.engine import make_engine
from memory.config import Settings
from memory.schemas import (
    Memory,
    MemoryCreate,
    MemoryPatch,
    RememberRequest,
    SearchHit,
    SearchRequest,
)
from memory.security.auth import (
    AccessDenied,
    Authenticator,
    Conflict,
    NotFound,
    context_for,
)
from memory.service import MemoryService
from models.providers import CompatibleEmbedding, CompatibleExtractor, HashEmbedding


def create_app(settings=None, service=None, auth=None):
    settings = settings or Settings()
    if service is None:
        if settings.embedding_backend not in {"compatible", "hash-test"}:
            raise ValueError("unsupported embedding backend")
        embedder = (
            HashEmbedding(settings.embedding_dimensions)
            if settings.embedding_backend == "hash-test"
            else CompatibleEmbedding(settings)
        )
        service = MemoryService(
            make_engine(settings.database_url),
            embedder,
            CompatibleExtractor(settings),
            settings,
        )
    auth = auth or Authenticator.from_file(settings.credentials_file)
    app = FastAPI(
        title="Persistent Agent Memory",
        version="0.1.0",
        description="Phase 1 foundation. Retrieved memory is untrusted data, not instructions.",
    )
    bearer = HTTPBearer(auto_error=False)
    from memory.security.gateway import RateLimiter

    limiter = RateLimiter()
    metrics = {"requests": 0, "latency_seconds": 0.0, "rate_limited": 0}

    @app.middleware("http")
    async def gateway(request, call_next):
        start = time.perf_counter()
        address = request.client.host if request.client else "unknown"
        if not limiter.allow(address):
            metrics["rate_limited"] += 1
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
                headers={"Retry-After": "60"},
            )
        response = await call_next(request)
        duration = time.perf_counter() - start
        metrics["requests"] += 1
        metrics["latency_seconds"] += duration
        logging.getLogger("memory.api").info(
            "request_complete",
            extra={"status": response.status_code, "duration_seconds": duration},
        )
        return response

    @app.exception_handler(httpx.HTTPError)
    async def provider_error(request, error):
        return JSONResponse(
            status_code=502, content={"detail": "model provider unavailable"}
        )

    @app.exception_handler(AccessDenied)
    async def denied(request: Request, error):
        return JSONResponse(status_code=403, content={"detail": "access denied"})

    @app.exception_handler(NotFound)
    async def missing(request: Request, error):
        return JSONResponse(status_code=404, content={"detail": "memory not found"})

    @app.exception_handler(Conflict)
    async def conflict(request: Request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(IntegrityError)
    async def integrity(request: Request, error):
        return JSONResponse(
            status_code=409,
            content={"detail": "conflicting memory or message identity"},
        )

    @app.exception_handler(ValueError)
    async def invalid(request: Request, error):
        return JSONResponse(
            status_code=422,
            content={"detail": "invalid memory proposal or model output"},
        )

    def authenticated(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        if credentials is None:
            raise HTTPException(
                401,
                "bearer credential required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return auth.authenticate(credentials.credentials)
        except AccessDenied:
            raise HTTPException(
                401, "invalid credentials", headers={"WWW-Authenticate": "Bearer"}
            ) from None

    def context(scope):
        def dependency(
            credential=Depends(authenticated),
            session_id: UUID = Header(alias="X-Session-ID"),
            purpose: str = Header(alias="X-Purpose", min_length=1, max_length=200),
        ):
            return context_for(credential, session_id, purpose, scope)

        return dependency

    read, write, remove = context("read"), context("write"), context("delete")

    @app.post("/v1/sessions/{completed_session_id}/complete")
    def session_complete(completed_session_id: UUID, ctx=Depends(write)):
        session_id = completed_session_id
        if session_id != ctx.session_id:
            raise AccessDenied()
        from workers.queue import JobQueue

        exported = service.export(ctx)
        ids = [
            memory["memory_id"]
            for memory in exported["memories"]
            if memory["source_session_id"] == str(session_id)
            and memory["source_type"] != "DERIVED"
        ]
        if not ids:
            return {"episode_job_id": None}
        job_id = JobQueue(service.engine).enqueue(
            ctx,
            "memory.episode",
            {"memory_ids": ids[:100]},
            "session:" + str(session_id),
        )
        return {"episode_job_id": str(job_id)}

    @app.get("/v1/metrics")
    def metrics_get(ctx=Depends(read)):
        with service.engine.begin() as db:
            from database.repositories.memory import SQLMemoryRepository

            SQLMemoryRepository(db, ctx)
        return dict(metrics)

    @app.get("/v1/user/{user_id}/memory")
    def user_export(user_id: UUID, ctx=Depends(read)):
        if user_id != ctx.user_id:
            raise AccessDenied()
        return service.export(ctx)

    @app.delete("/v1/user/{user_id}/memory")
    def user_delete(user_id: UUID, ctx=Depends(remove)):
        if user_id != ctx.user_id:
            raise AccessDenied()
        return service.delete_namespace_memory(ctx)

    @app.post("/v1/memory/{memory_id}/explain")
    def memory_explain(memory_id: UUID, ctx=Depends(read)):
        memory = service.get(ctx, memory_id)
        return {
            "memory": memory,
            "provenance": service.provenance(ctx, memory_id),
            "epistemic_type": memory.epistemic_type,
            "truth_confidence": memory.truth_confidence,
            "explanation": "Stored from attributed source or derived from the linked evidence; retrieval frequency does not establish truth.",
        }

    from memory.episodes.service import Episode, EpisodeInput, EpisodeService

    episodes = EpisodeService(service)
    from memory.experiences.service import (
        CompileRequest,
        Experience,
        ExperienceQuery,
        ExperienceService,
    )

    experiences = ExperienceService(service)
    from memory.procedures.service import (
        Procedure,
        ProcedureCompile,
        ProcedureFeedback,
        ProcedureService,
    )

    procedures = ProcedureService(service)
    from memory.context.transfer import ContextRequest, ContextTransferService
    from memory.goals.service import GoalInput, GoalPatch, GoalService

    transfer_service = ContextTransferService(service)
    goal_service = GoalService(service)
    from memory.entities.service import EntityService

    entities = EntityService(service)

    @app.get("/v1/entities/{entity_id}")
    def entity_get(entity_id: UUID, ctx=Depends(read)):
        return entities.get(ctx, entity_id)

    @app.post("/v1/entities/search")
    def entity_search(body: SearchRequest, ctx=Depends(read)):
        return entities.search(ctx, body)

    from memory.reflection.engine import ReflectionEngine

    reflection = ReflectionEngine(service)
    from memory.decay.service import DynamicsService
    from memory.goals.prospective import LoopInput, ProspectiveInput, ProspectiveService

    dynamics = DynamicsService(service)
    prospective = ProspectiveService(service)

    @app.post("/v1/memory/{memory_id}/pin", response_model=Memory)
    def memory_pin(memory_id: UUID, ctx=Depends(write)):
        return dynamics.pin(ctx, memory_id)

    @app.post("/v1/prospective", status_code=201)
    def prospective_create(body: ProspectiveInput, ctx=Depends(write)):
        return prospective.create(ctx, body)

    @app.post("/v1/open-loops", status_code=201)
    def loop_create(body: LoopInput, ctx=Depends(write)):
        return prospective.open_loop(ctx, body)

    from memory.serendipity.engine import SerendipityEngine

    @app.post("/v1/serendipity/run")
    def serendipity_run(ctx=Depends(write)):
        return SerendipityEngine(service).run(ctx)

    @app.post("/v1/reflection/run")
    def reflection_run(ctx=Depends(write)):
        return reflection.run(ctx)

    @app.get("/v1/insights")
    def insights_get(ctx=Depends(read)):
        return reflection.list(ctx)

    @app.post("/v1/context/build")
    def context_build(body: ContextRequest, ctx=Depends(read)):
        return transfer_service.build(ctx, body)

    @app.post("/v1/context/transfer")
    def context_transfer(body: ContextRequest, ctx=Depends(read)):
        return transfer_service.transfer(ctx, body)

    @app.get("/v1/goals")
    def goals_get(ctx=Depends(read)):
        return goal_service.list(ctx)

    @app.post("/v1/goals", status_code=201)
    def goal_create(body: GoalInput, ctx=Depends(write)):
        return goal_service.create(ctx, body)

    @app.patch("/v1/goals/{goal_id}")
    def goal_patch(goal_id: UUID, body: GoalPatch, ctx=Depends(write)):
        return goal_service.patch(ctx, goal_id, body)

    @app.post("/v1/procedures/compile", response_model=Procedure)
    def procedure_compile(body: ProcedureCompile, ctx=Depends(write)):
        return procedures.compile(ctx, body)

    @app.get("/v1/procedures/{procedure_id}", response_model=Procedure)
    def procedure_get(procedure_id: UUID, ctx=Depends(read)):
        return procedures.get(ctx, procedure_id)

    @app.post("/v1/procedures/search")
    def procedure_search(body: ExperienceQuery, ctx=Depends(read)):
        return procedures.search(ctx, body)

    @app.post("/v1/procedures/{procedure_id}/feedback", response_model=Procedure)
    def procedure_feedback(
        procedure_id: UUID, body: ProcedureFeedback, ctx=Depends(write)
    ):
        return procedures.feedback(ctx, procedure_id, body)

    @app.post("/v1/experiences/compile", response_model=Experience)
    def experience_compile(body: CompileRequest, ctx=Depends(write)):
        return experiences.compile(ctx, body.episode_ids)

    @app.get("/v1/experiences/{experience_id}", response_model=Experience)
    def experience_get(experience_id: UUID, ctx=Depends(read)):
        return experiences.get(ctx, experience_id)

    @app.post("/v1/experiences/search")
    def experience_search(body: ExperienceQuery, ctx=Depends(read)):
        return experiences.search(ctx, body)

    @app.post("/v1/episodes", response_model=Episode, status_code=201)
    def episode_create(body: EpisodeInput, ctx=Depends(write)):
        return episodes.record(ctx, body)

    @app.get("/v1/episodes/{episode_id}", response_model=Episode)
    def episode_get(episode_id: UUID, ctx=Depends(read)):
        return episodes.get(ctx, episode_id)

    @app.post("/v1/episodes/search")
    def episode_search(body: SearchRequest, ctx=Depends(read)):
        return episodes.search(ctx, body)

    @app.get("/health/live")
    def live():
        return {"status": "alive", "phase": 1}

    @app.post("/v1/memory", response_model=Memory, status_code=201)
    def create(body: MemoryCreate, ctx=Depends(write)):
        return service.create(ctx, body)

    @app.post("/v1/memory/search", response_model=list[SearchHit])
    def search(body: SearchRequest, ctx=Depends(read)):
        return service.search(ctx, body)

    @app.post("/v1/memory/remember", response_model=list[Memory])
    def remember(body: RememberRequest, ctx=Depends(write)):
        return service.remember(ctx, body)

    from memory.mutation.engine import MutationRequest

    @app.post("/v1/memory/mutate", response_model=Memory | None)
    def mutate(body: MutationRequest, ctx=Depends(write)):
        return service.mutate(ctx, body)

    @app.post("/v1/memory/{memory_id}/correct", response_model=Memory)
    def correct(memory_id: UUID, body: MutationRequest, ctx=Depends(write)):
        from memory.mutation.engine import MutationKind

        if body.target_id != memory_id or body.operation != MutationKind.CORRECTION:
            raise ValueError("correction must explicitly target the requested memory")
        return service.mutate(ctx, body)

    @app.get("/v1/memory/{memory_id}", response_model=Memory)
    def get(memory_id: UUID, ctx=Depends(read)):
        return service.get(ctx, memory_id)

    @app.patch("/v1/memory/{memory_id}", response_model=Memory)
    def patch(memory_id: UUID, body: MemoryPatch, ctx=Depends(write)):
        return service.patch(ctx, memory_id, body)

    @app.delete("/v1/memory/{memory_id}", status_code=204)
    def delete(memory_id: UUID, ctx=Depends(remove)):
        service.delete(ctx, memory_id)
        return Response(status_code=204)

    @app.get("/v1/provenance/{memory_id}")
    def provenance(memory_id: UUID, ctx=Depends(read)):
        return {
            "memory_id": str(memory_id),
            "edges": service.provenance(ctx, memory_id),
        }

    return app
