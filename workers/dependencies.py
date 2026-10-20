"""Content-free evidence references; legacy raw payloads are handled conservatively."""

from uuid import UUID

from sqlalchemy import select, update

from database.operations_tables import jobs
from memory.security.identifiers import job_key

MEMORY_KEYS = {
    "task_id",
    "goal_id",
    "memory_id",
    "memory_ids",
    "episode_id",
    "episode_ids",
    "experience_id",
    "experience_ids",
    "insight_id",
    "procedure_id",
    "provenance_ids",
    "supporting_memory_ids",
    "counterexample_memory_ids",
}
SOURCE_KEYS = {"source_id", "source_ids", "source_message_id", "message_id"}
NAMESPACE_READERS = {
    "autonomy.tick",
    "memory.reflect",
    "memory.validate",
    "memory.serendipity",
    "memory.consolidate",
    "memory.decay",
    "DREAMER",
    "memory.summarize",
}


def references(queue, ctx, payload):
    refs = {
        "version": 1,
        "memory_ids": [],
        "source_ids": [],
        "session_ids": [],
        "namespace_read": queue in NAMESPACE_READERS,
    }

    def collect(value, destination):
        for item in value if isinstance(value, list) else [value]:
            try:
                destination.append(str(UUID(str(item))))
            except (ValueError, TypeError, AttributeError):
                pass

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in MEMORY_KEYS:
                    collect(item, refs["memory_ids"])
                elif key in SOURCE_KEYS:
                    collect(item, refs["source_ids"])
                elif key in {"session_id", "source_session_id"}:
                    collect(item, refs["session_ids"])
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    if queue in {"memory.extract", "memory.agent_turn"}:
        refs["session_ids"].append(str(ctx.session_id))
    for name in ("memory_ids", "source_ids", "session_ids"):
        refs[name] = sorted(set(refs[name]))
    return refs


def scrub_turns(repo, memory_ids, session_ids):
    from database.cognitive_tables import turns

    identities = set(map(str, memory_ids))
    sessions = set(session_ids)
    rows = (
        repo.db.execute(
            select(turns).where(turns.c.namespace_id == repo.ctx.namespace_id)
        )
        .mappings()
        .all()
    )
    scrubbed = set()
    while True:
        changed = False
        for row in rows:
            if row["id"] in scrubbed:
                continue
            refs = set(row["context_refs"])
            retained = set((row["response"] or {}).get("memory_ids", []))
            if row["session_id"] in sessions or identities.intersection(
                refs | retained
            ):
                sessions.add(row["session_id"])
                scrubbed.add(row["id"])
                repo.db.execute(
                    update(turns)
                    .where(turns.c.id == row["id"])
                    .values(
                        status="CANCELLED", payload={}, response=None, context_refs={}
                    )
                )
                changed = True
        if not changed:
            break
    scrub_autonomous_tasks(repo, identities, sessions)
    return sessions


def scrub_autonomous_tasks(repo, identities, sessions):
    """Clear task caches before canonical FK cascades and fence in-flight runs."""
    from uuid import uuid4

    from database.autonomy_tables import runs, tasks

    affected = set()
    for row in repo.db.execute(
        select(tasks).where(tasks.c.namespace_id == repo.ctx.namespace_id)
    ).mappings():
        context = row["execution_context"]
        refs = set(row["payload"].get("approved_revisions", {}))
        if (
            str(row["id"]) in identities
            or identities.intersection(refs)
            or context.get("session_id") in set(map(str, sessions))
        ):
            affected.add(row["id"])
    for row in repo.db.execute(
        select(runs).where(runs.c.namespace_id == repo.ctx.namespace_id)
    ).mappings():
        if identities.intersection(row["payload"].get("context_refs", {})):
            affected.add(row["task_id"])
    if affected:
        repo.db.execute(
            update(tasks)
            .where(tasks.c.id.in_(affected))
            .values(
                status="CANCELLED", payload={}, execution_context={}, next_run_at=None
            )
        )
        repo.db.execute(
            update(runs)
            .where(runs.c.task_id.in_(affected))
            .values(status="CANCELLED", payload={}, lease_token=uuid4())
        )


def cancel_for_erasure(repo, memory_ids, source_ids, session_ids):
    memory_ids, source_ids, session_ids = map(
        lambda items: set(map(str, items)), (memory_ids, source_ids, session_ids)
    )
    count = 0
    rows = (
        repo.db.execute(
            select(jobs).where(jobs.c.namespace_id == repo.ctx.namespace_id)
        )
        .mappings()
        .all()
    )
    for row in rows:
        refs = row["dependencies"] or {}
        legacy = not refs.get("version")
        if legacy:
            from memory.schemas import RequestContext

            context = row["payload"].get("context", {})
            try:
                refs = references(
                    row["queue"],
                    RequestContext.model_validate(context),
                    row["payload"].get("input", {}),
                )
            except ValueError:
                refs = {}
        affected = (
            bool(memory_ids.intersection(refs.get("memory_ids", [])))
            or bool(source_ids.intersection(refs.get("source_ids", [])))
            or bool(session_ids.intersection(refs.get("session_ids", [])))
            or (refs.get("namespace_read") and row["status"] in {"PENDING", "RUNNING"})
            or (legacy and row["queue"] == "memory.extract")
        )
        if affected:
            stored_key = row["idempotency_key"]
            if (row["dependencies"] or {}).get("key_format") != "hashed-v1":
                stored_key = job_key(
                    repo.ctx.namespace_id,
                    stored_key.removeprefix(f"{repo.ctx.namespace_id}:"),
                )
            refs = {**refs, "key_format": "hashed-v1"}
            # Retain only operational identity and references. Clearing the lease
            # prevents an in-flight completion from restoring payload or status.
            repo.db.execute(
                update(jobs)
                .where(jobs.c.id == row["id"])
                .values(
                    status="CANCELLED",
                    idempotency_key=stored_key,
                    payload={},
                    lease_token=None,
                    lease_until=None,
                    last_error="EvidenceDeleted",
                    dependencies=refs,
                )
            )
            count += 1
    return count
