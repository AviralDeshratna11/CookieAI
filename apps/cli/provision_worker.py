"""Provision an idempotent read/write-only service agent for the local namespace."""

import json
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import insert

from database import tables as t
from database.engine import make_engine
from memory.config import Settings
from memory.schemas import RequestContext


def main():
    settings = Settings()
    path = Path("config/worker-context.json")
    if path.exists():
        RequestContext.model_validate_json(path.read_text(encoding="utf-8"))
        print("Worker identity already provisioned.")
        return
    credential = json.loads(settings.credentials_file.read_text(encoding="utf-8"))[0]
    agent = uuid4()
    ctx = RequestContext(
        user_id=UUID(credential["user_id"]),
        requesting_agent_id=agent,
        namespace_id=UUID(credential["namespace_id"]),
        session_id=uuid4(),
        purpose="Authorized background memory discovery",
        requested_scope="write",
    )
    engine = make_engine(settings.migration_database_url or settings.database_url)
    with engine.begin() as db:
        db.execute(insert(t.agents).values(id=agent, user_id=ctx.user_id))
        db.execute(
            insert(t.grants).values(
                namespace_id=ctx.namespace_id,
                agent_id=agent,
                can_read=True,
                can_write=True,
                can_delete=False,
            )
        )
        with path.open("x", encoding="utf-8") as handle:
            handle.write(ctx.model_dump_json(indent=2))
    print(
        "Separate worker identity provisioned with read/write grants; no delete grant."
    )


if __name__ == "__main__":
    main()
