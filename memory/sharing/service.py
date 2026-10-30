"""Cross-user namespace sharing. A grant exposes only SHARED-flagged memories
in the granting namespace to another user; see database/repositories/memory.py
`shared_memories`/`shareable` for the read-time enforcement."""

from uuid import UUID, uuid4

from sqlalchemy import select, update

from database import sharing_tables as s
from database.repositories.memory import SQLMemoryRepository
from memory.schemas import StrictModel, utcnow
from memory.security.auth import NotFound, require_scope


class ShareInput(StrictModel):
    grantee_user_id: UUID
    can_read: bool = True


def _row(row):
    return {
        "share_id": str(row["id"]),
        "namespace_id": str(row["namespace_id"]),
        "grantee_user_id": str(row["grantee_user_id"]),
        "granted_by_user_id": str(row["granted_by_user_id"]),
        "can_read": row["can_read"],
        "created_at": row["created_at"].isoformat(),
        "revoked_at": row["revoked_at"].isoformat() if row["revoked_at"] else None,
        "active": row["revoked_at"] is None,
    }


class SharingService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def grant(self, ctx, body: ShareInput):
        if body.grantee_user_id == ctx.user_id:
            raise ValueError("cannot share a namespace with yourself")
        with self.memory.engine.begin() as db:
            SQLMemoryRepository(db, ctx)  # authorize before writing a grant
            existing = (
                db.execute(
                    select(s.shares).where(
                        s.shares.c.namespace_id == ctx.namespace_id,
                        s.shares.c.grantee_user_id == body.grantee_user_id,
                        s.shares.c.revoked_at.is_(None),
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                db.execute(
                    update(s.shares)
                    .where(s.shares.c.id == existing["id"])
                    .values(can_read=body.can_read)
                )
                return _row({**existing, "can_read": body.can_read})
            row = {
                "id": uuid4(),
                "namespace_id": ctx.namespace_id,
                "grantee_user_id": body.grantee_user_id,
                "granted_by_user_id": ctx.user_id,
                "can_read": body.can_read,
                "created_at": utcnow(),
                "revoked_at": None,
            }
            db.execute(s.shares.insert().values(**row))
            return _row(row)

    @require_scope("write")
    def revoke(self, ctx, share_id: UUID):
        with self.memory.engine.begin() as db:
            SQLMemoryRepository(db, ctx)  # authorize before writing
            changed = db.execute(
                update(s.shares)
                .where(
                    s.shares.c.id == share_id,
                    s.shares.c.namespace_id == ctx.namespace_id,
                    s.shares.c.revoked_at.is_(None),
                )
                .values(revoked_at=utcnow())
            )
            if not changed.rowcount:
                raise NotFound("share not found")
            return {"share_id": str(share_id), "revoked": True}

    @require_scope("read")
    def outgoing(self, ctx):
        with self.memory.engine.begin() as db:
            SQLMemoryRepository(db, ctx)  # authorize before reading
            rows = (
                db.execute(
                    select(s.shares)
                    .where(s.shares.c.namespace_id == ctx.namespace_id)
                    .order_by(s.shares.c.created_at.desc())
                )
                .mappings()
                .all()
            )
            return [_row(row) for row in rows]

    @require_scope("read")
    def incoming(self, ctx):
        with self.memory.engine.begin() as db:
            SQLMemoryRepository(db, ctx)  # authorize before reading
            rows = (
                db.execute(
                    select(s.shares)
                    .where(
                        s.shares.c.grantee_user_id == ctx.user_id,
                        s.shares.c.revoked_at.is_(None),
                    )
                    .order_by(s.shares.c.created_at.desc())
                )
                .mappings()
                .all()
            )
            return [_row(row) for row in rows]
