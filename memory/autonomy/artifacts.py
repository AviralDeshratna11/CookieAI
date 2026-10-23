"""Remove workspace projections before canonical erasure commits.

An OS error aborts canonical deletion. Partial file removal reduces availability;
host crashes and backups require separate operational recovery.
"""

from pathlib import Path

from sqlalchemy import select

from database import autonomy_tables as a
from memory.autonomy.handoff import safe_path


def erase_files(repo, removed):
    workspace = getattr(repo, "artifact_workspace", None)
    if workspace is None:
        return
    files = []
    for identity in removed:
        source = repo.get(identity)
        if "handoff:source" in source.tags:
            files.append((source.source_agent_id, f"inputs/{identity}.txt"))
    rows = repo.db.execute(
        select(a.tasks.c.agent_id, a.runs.c.id)
        .join(a.runs, a.runs.c.task_id == a.tasks.c.id)
        .where(
            a.tasks.c.id.in_(removed), a.tasks.c.namespace_id == repo.ctx.namespace_id
        )
    ).all()
    files.extend((row.agent_id, f"outputs/{row.id}.json") for row in rows)
    for agent_id, relative in files:
        root = Path(workspace) / str(repo.ctx.namespace_id) / str(agent_id)
        if not root.exists():
            continue
        path = safe_path(root, relative)
        path.unlink(missing_ok=True)
        pending = path.with_name(path.name + ".pending")
        if pending.is_symlink():
            raise PermissionError("Linked pending artifact cannot be erased")
        pending.unlink(missing_ok=True)
