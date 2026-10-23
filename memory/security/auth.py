import hashlib
import hmac
import json
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from uuid import UUID

from memory.schemas import RequestContext


class AccessDenied(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def require_scope(scope):
    """Domain entry points derive permission from the operation, never caller-selected scope."""

    def decorate(function):
        @wraps(function)
        def checked(self, ctx, *args, **kwargs):
            from memory.security.disclosure import disclosure_scope

            scoped = ctx.model_copy(update={"requested_scope": scope})
            memory = getattr(self, "memory", self)
            if not hasattr(memory, "engine"):
                return function(self, scoped, *args, **kwargs)
            with disclosure_scope(memory, scoped):
                return function(self, scoped, *args, **kwargs)

        return checked

    return decorate


@dataclass(frozen=True)
class Credential:
    token_sha256: str
    user_id: UUID
    agent_id: UUID
    namespace_id: UUID
    project_ids: tuple[UUID, ...] = ()


class Authenticator:
    def __init__(self, credentials: list[Credential]):
        self.credentials = credentials

    @classmethod
    def from_file(cls, path: Path):
        if not path.exists():
            return cls([])  # No credentials means all access is denied.
        rows = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            [
                Credential(
                    r["token_sha256"],
                    UUID(r["user_id"]),
                    UUID(r["agent_id"]),
                    UUID(r["namespace_id"]),
                    tuple(UUID(item) for item in r.get("project_ids", [])),
                )
                for r in rows
            ]
        )

    def authenticate(self, token: str) -> Credential:
        digest = hashlib.sha256(token.encode()).hexdigest()
        for credential in self.credentials:
            if hmac.compare_digest(credential.token_sha256, digest):
                return credential
        raise AccessDenied("invalid credentials")


def context_for(credential, session_id, purpose, scope):
    return RequestContext(
        user_id=credential.user_id,
        requesting_agent_id=credential.agent_id,
        namespace_id=credential.namespace_id,
        session_id=session_id,
        purpose=purpose,
        requested_scope=scope,
        project_ids=list(credential.project_ids),
    )
