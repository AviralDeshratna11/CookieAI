"""Durable at-least-once jobs, SQL leases, bounded retries and caller identity."""

from contextlib import nullcontext
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, case, insert, or_, select, update

from database import operations_tables as o
from memory.schemas import utcnow
from memory.security.identifiers import job_key

QUEUES = set(
    "memory.extract memory.embed memory.graph memory.episode memory.experience memory.consolidate memory.reflect memory.serendipity memory.validate memory.decay memory.reindex memory.delete memory.summarize memory.agent_turn autonomy.tick autonomy.run DREAMER".split()
)


class JobQueue:
    def __init__(self, engine, context=None):
        self.engine = engine
        self.context = context

    def enqueue(
        self, ctx, queue, payload, idempotency_key, priority=5, connection=None
    ):
        from database.repositories.memory import SQLMemoryRepository

        if queue not in QUEUES:
            raise ValueError("unknown background queue")
        ctx = ctx.model_copy(
            update={
                "requested_scope": "delete" if queue == "memory.delete" else "write"
            }
        )
        if len(idempotency_key) > 128:
            raise ValueError("idempotency key exceeds 128 characters")
        legacy_key = f"{ctx.namespace_id}:{idempotency_key}"
        idempotency_key = job_key(ctx.namespace_id, idempotency_key)
        with (
            nullcontext(connection) if connection is not None else self.engine.begin()
        ) as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            existing = db.execute(
                select(o.jobs.c.id).where(
                    o.jobs.c.idempotency_key.in_([idempotency_key, legacy_key]),
                    o.jobs.c.namespace_id == ctx.namespace_id,
                )
            ).scalar()
            if existing:
                return existing
            job_id = uuid4()
            from workers.dependencies import references

            db.execute(
                insert(o.jobs).values(
                    id=job_id,
                    namespace_id=ctx.namespace_id,
                    idempotency_key=idempotency_key,
                    queue=queue,
                    payload={"context": ctx.model_dump(mode="json"), "input": payload},
                    status="PENDING",
                    retry_count=0,
                    priority=priority,
                    created_at=utcnow(),
                    available_at=utcnow(),
                    dependencies={
                        **references(queue, ctx, payload),
                        "key_format": "hashed-v1",
                    },
                )
            )
            return job_id

    def claim(self):
        with self.engine.begin() as db:
            if self.context:
                from database.repositories.memory import SQLMemoryRepository

                SQLMemoryRepository(db, self.context)
            now = utcnow()
            statement = (
                select(o.jobs)
                .where(
                    or_(
                        and_(
                            o.jobs.c.status == "PENDING", o.jobs.c.available_at <= now
                        ),
                        and_(o.jobs.c.status == "RUNNING", o.jobs.c.lease_until < now),
                    )
                )
                .order_by(
                    case(
                        (o.jobs.c.created_at <= now - timedelta(minutes=10), 0),
                        else_=o.jobs.c.priority,
                    ),
                    o.jobs.c.created_at,
                )
                .limit(1)
            )
            if self.context:
                statement = statement.where(
                    o.jobs.c.namespace_id == self.context.namespace_id
                )
            if db.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            row = db.execute(statement).mappings().first()
            if not row:
                return None
            token = uuid4()
            db.execute(
                update(o.jobs)
                .where(o.jobs.c.id == row["id"])
                .values(
                    status="RUNNING",
                    lease_token=token,
                    lease_until=now + timedelta(minutes=10),
                    started_at=now,
                    finished_at=None,
                )
            )
            return {**row, "lease_token": token}

    def finish(self, job, error=None):
        with self.engine.begin() as db:
            if db.dialect.name == "postgresql":
                from sqlalchemy import text

                db.execute(
                    text("SELECT set_config('memory.namespace_id',:namespace,true)"),
                    {"namespace": str(job["namespace_id"])},
                )
            attempts = job["retry_count"] + int(error is not None)
            status = (
                "DONE" if error is None else "FAILED" if attempts >= 5 else "PENDING"
            )
            response = getattr(error, "response", None)
            limited = response is not None and response.status_code == 429
            delay = min(300, 2**attempts)
            if limited:
                try:
                    delay = max(
                        60, min(900, int(response.headers.get("Retry-After", "60")))
                    )
                except ValueError:
                    delay = 60
            # Log only exception class; model/source content must not become queue-error text.
            db.execute(
                update(o.jobs)
                .where(
                    o.jobs.c.id == job["id"], o.jobs.c.lease_token == job["lease_token"]
                )
                .values(
                    status=status,
                    retry_count=attempts,
                    last_error="ProviderRateLimited"
                    if limited
                    else type(error).__name__
                    if error
                    else None,
                    finished_at=utcnow() if status in {"DONE", "FAILED"} else None,
                    lease_until=None,
                    lease_token=None,
                    available_at=utcnow() + timedelta(seconds=delay),
                )
            )

    def renew(self, job):
        """Renew only a currently owned lease; a canceled/reclaimed job stays canceled."""
        with self.engine.begin() as db:
            if db.dialect.name == "postgresql":
                from sqlalchemy import text

                db.execute(text("SET LOCAL lock_timeout='2s'"))
                db.execute(
                    text("SELECT set_config('memory.namespace_id',:namespace,true)"),
                    {"namespace": str(job["namespace_id"])},
                )
            result = db.execute(
                update(o.jobs)
                .where(
                    o.jobs.c.id == job["id"],
                    o.jobs.c.status == "RUNNING",
                    o.jobs.c.lease_token == job["lease_token"],
                )
                .values(lease_until=utcnow() + timedelta(minutes=10))
            )
            return result.rowcount == 1
