"""Namespace-scoped job progress without exposing input payloads or stored text."""

from sqlalchemy import func, select

from database.operations_tables import jobs
from database.repositories.memory import SQLMemoryRepository
from memory.schemas import utcnow
from memory.security.auth import require_scope


class OperationsService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("read")
    def status(self, ctx):
        with self.memory.engine.begin() as db:
            SQLMemoryRepository(db, ctx)
            counts = db.execute(
                select(jobs.c.queue, jobs.c.status, func.count())
                .where(jobs.c.namespace_id == ctx.namespace_id)
                .group_by(jobs.c.queue, jobs.c.status)
            ).all()
            oldest = db.execute(
                select(func.min(jobs.c.created_at)).where(
                    jobs.c.namespace_id == ctx.namespace_id, jobs.c.status == "PENDING"
                )
            ).scalar()
            finished = db.execute(
                select(func.max(jobs.c.finished_at)).where(
                    jobs.c.namespace_id == ctx.namespace_id, jobs.c.status == "DONE"
                )
            ).scalar()
        from datetime import timezone

        if oldest is not None and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        workers = []
        redis_state = "available"
        try:
            import redis

            connection = redis.Redis.from_url(
                self.memory.settings.redis_url,
                socket_timeout=3,
                socket_connect_timeout=3,
                decode_responses=True,
            )
            try:
                for index, key in enumerate(
                    connection.scan_iter(
                        match=f"memory.worker.progress:{ctx.namespace_id}:*", count=20
                    )
                ):
                    if index >= 20:
                        break
                    values = connection.hgetall(key)
                    import time

                    age = time.time() - float(values.get("updated_at", "0"))
                    workers.append(
                        {
                            "stage": values.get("stage"),
                            "progress_age_seconds": max(0, age),
                            "stalled": age > self.memory.settings.worker_stall_seconds,
                        }
                    )
            finally:
                connection.close()
        except Exception:
            redis_state = "unavailable"
        return {
            "counts": [{"queue": q, "status": s, "count": n} for q, s, n in counts],
            "oldest_pending_age_seconds": max(0, (utcnow() - oldest).total_seconds())
            if oldest
            else None,
            "last_successful_job_at": finished.isoformat() if finished else None,
            "workers": workers,
            "redis": redis_state,
            "stalled_work_is_healthy": False,
        }
