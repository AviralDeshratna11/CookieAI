"""Provision a local user/agent/namespace. Prints the raw token exactly once."""

import hashlib
import json
import secrets
from uuid import uuid4

from sqlalchemy import insert

from database import tables as t
from database.engine import make_engine
from memory.config import Settings


def main():
    settings = Settings()
    path = settings.credentials_file
    if path.exists():
        raise SystemExit(
            "Credential file already exists; refusing to overwrite credentials."
        )
    user_id, agent_id, namespace_id = uuid4(), uuid4(), uuid4()
    token = secrets.token_urlsafe(32)
    credential = {
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "user_id": str(user_id),
        "agent_id": str(agent_id),
        "namespace_id": str(namespace_id),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.migration_database_url or settings.database_url)
    with engine.begin() as db:
        db.execute(insert(t.users).values(id=user_id))
        db.execute(insert(t.agents).values(id=agent_id, user_id=user_id))
        db.execute(
            insert(t.namespaces).values(
                id=namespace_id, owner_id=user_id, kind="USER_PRIVATE"
            )
        )
        db.execute(
            insert(t.grants).values(
                namespace_id=namespace_id,
                agent_id=agent_id,
                can_read=True,
                can_write=True,
                can_delete=True,
            )
        )
        # Exclusive create prevents silently replacing a concurrent bootstrap.
        with path.open("x", encoding="utf-8") as handle:
            json.dump([credential], handle, indent=2)
    print("Store this bearer token securely; it is not written to disk:")
    print(token)
    print("Namespace:", namespace_id)


if __name__ == "__main__":
    main()
