import logging
from threading import Event, Thread
from uuid import UUID

from sqlalchemy import select

from database.repositories.memory import SQLMemoryRepository
from memory.schemas import RememberRequest, RequestContext
from memory.security.auth import NotFound
from workers.queue import JobQueue

log = logging.getLogger("memory.worker")


class Worker:
    def __init__(self, memory, context=None):
        self.memory = memory
        self.queue = JobQueue(memory.engine, context)

    def execute(self, queue, ctx, payload):
        from memory.security.disclosure import disclosure_scope

        with disclosure_scope(self.memory, ctx):
            return self._execute(queue, ctx, payload)

    def _execute(self, queue, ctx, payload):
        if queue in {"autonomy.tick", "autonomy.run"}:
            from memory.autonomy.service import TaskSupervisor

            supervisor = TaskSupervisor(self.memory)
            return (
                supervisor.tick(ctx)
                if queue == "autonomy.tick"
                else supervisor.process(ctx, UUID(payload["task_id"]))
            )
        if queue == "memory.agent_turn":
            from memory.agent.service import AgentService

            return AgentService(self.memory).process(ctx, UUID(payload["turn_id"]))
        if queue == "memory.summarize":
            from memory.context.continuity import ContinuityService

            return ContinuityService(self.memory).build(ctx)
        from memory.decay.service import DynamicsService
        from memory.episodes.service import EpisodeService
        from memory.reflection.engine import ReflectionEngine
        from memory.serendipity.engine import SerendipityEngine

        if queue == "memory.extract":
            return self.memory.remember(ctx, RememberRequest.model_validate(payload))
        if queue == "memory.episode":
            return EpisodeService(self.memory).segment(
                ctx, [UUID(item) for item in payload["memory_ids"]]
            )
        if queue == "memory.experience":
            from database import learning_tables as episode_tables
            from memory.episodes.service import Episode
            from memory.experiences.service import (
                ExperienceService,
                fingerprint,
                structural_similarity,
            )
            from memory.procedures.service import ProcedureCompile, ProcedureService

            anchor = EpisodeService(self.memory).get(ctx, UUID(payload["episode_id"]))
            ids = [anchor.episode_id]
            with self.memory.engine.begin() as db:
                repo = SQLMemoryRepository(db, ctx)
                for row in db.execute(select(episode_tables.episodes)):
                    if row.id == anchor.episode_id:
                        continue
                    try:
                        repo.get(row.id)
                    except NotFound:
                        continue
                    other = Episode.model_validate(row.payload)
                    if other.evidence_origin != anchor.evidence_origin:
                        continue
                    if (
                        structural_similarity(fingerprint(anchor), fingerprint(other))
                        >= 0.65
                    ):
                        ids.append(row.id)
                    if len(ids) >= 100:
                        break
            experience = ExperienceService(self.memory).compile(ctx, ids)
            if len(ids) >= 3 and experience.successful_actions:
                try:
                    ProcedureService(self.memory).compile(
                        ctx, ProcedureCompile(experience_ids=[experience.experience_id])
                    )
                except ValueError:
                    # Retain a useful experience even if observed action order
                    # does not justify a reusable procedure.
                    log.info("procedure_not_supported_by_observed_sequences")
            return experience
        if queue in {"memory.reflect", "memory.validate"}:
            return ReflectionEngine(self.memory).run(ctx)
        if queue == "memory.serendipity":
            return SerendipityEngine(self.memory).run(ctx)
        if queue == "memory.decay":
            return DynamicsService(self.memory).decay(ctx)
        if queue == "memory.consolidate":
            return DynamicsService(self.memory).cluster(ctx)
        if queue == "DREAMER":
            clusters = DynamicsService(self.memory).cluster(ctx)
            reflected = ReflectionEngine(self.memory).run(ctx)
            explored = SerendipityEngine(self.memory).run(ctx)
            return {
                "clusters": len(clusters),
                "reflected": len(reflected),
                "explored": len(explored),
            }
        if queue == "memory.delete":
            try:
                return self.memory.delete(ctx, UUID(payload["memory_id"]))
            except NotFound:
                return []
        if queue in {"memory.embed", "memory.graph", "memory.reindex"}:
            from memory.entities.store import project
            from memory.graph.service import sync
            from memory.schemas import Memory, utcnow

            with self.memory.engine.begin() as db:
                repo = SQLMemoryRepository(db, ctx)
                repo.lock_namespace()
                try:
                    memory = repo.get(UUID(payload["memory_id"]))
                except NotFound:
                    return None
                if queue in {"memory.embed", "memory.reindex"}:
                    values = memory.model_dump()
                    values.update(
                        embedding_model=self.memory.embedder.model_id,
                        embedding_version=self.memory.embedder.version,
                        revision=memory.revision + 1,
                        updated_at=utcnow(),
                    )
                    memory = Memory.model_validate(values)
                    repo.save(
                        memory, self.memory.vector(memory.canonical_text), "UPDATED"
                    )
                    project(repo, memory, self.memory.embedder)
                sync(repo, memory)
                return memory.memory_id
        raise ValueError("unsupported queue")

    def run_once(self):
        job = self.queue.claim()
        if not job:
            return False
        stopping = Event()

        def heartbeat():
            while not stopping.wait(60):
                try:
                    if not self.queue.renew(job):
                        return
                except Exception as error:
                    log.warning("lease_renewal_failed: %s", type(error).__name__)

        renewer = Thread(target=heartbeat, daemon=True)
        renewer.start()
        try:
            log.info("job_started: %s %s", job["queue"], job["id"])
            context = RequestContext.model_validate(job["payload"]["context"])
            context = context.model_copy(
                update={
                    "execution_job_id": job["id"],
                    "execution_lease_token": job["lease_token"],
                }
            )
            # Revalidate current grants at execution; serialized context is never an ACL override.
            with self.memory.engine.begin() as db:
                SQLMemoryRepository(db, context)
            self.execute(job["queue"], context, job["payload"]["input"])
        except Exception as error:
            self.queue.finish(job, error)
            log.warning(
                "job_failed",
                extra={"job_id": str(job["id"]), "error_type": type(error).__name__},
            )
        else:
            self.queue.finish(job)
            log.info("job_completed: %s %s", job["queue"], job["id"])
        finally:
            stopping.set()
            renewer.join(timeout=3)
        return True
