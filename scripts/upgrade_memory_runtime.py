"""Back up and atomically upgrade the existing hosted schema; never copies data.

Stop API/worker writers first. On failure the migration transaction rolls back;
restart the preceding image. The private dump is a separate disaster-recovery path.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

from apps.cli.check_hosted import validate_url
from scripts.backup_hosted import main as backup


def identity_digest(db):
    ids = (
        db.execute(text("SELECT id::text FROM public.memories ORDER BY id"))
        .scalars()
        .all()
    )
    return {
        "count": len(ids),
        "sha256": hashlib.sha256("|".join(ids).encode()).hexdigest(),
    }


def main():
    backup()
    values = dotenv_values(".env.supabase")
    engine = create_engine(
        validate_url(values["MEMORY_HOSTED_MIGRATION_DATABASE_URL"]),
        connect_args={"connect_timeout": 20},
    )
    report = {"at": datetime.now(timezone.utc).isoformat()}
    try:
        with engine.begin() as db:
            db.execute(text("SET LOCAL search_path TO public,extensions"))
            db.execute(text("SET LOCAL lock_timeout='15s'"))
            report["before"] = identity_digest(db)
            report["previous_revision"] = db.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = db
            command.upgrade(cfg, "head")
            for name in ("continuity_snapshots", "agent_turns"):
                db.execute(
                    text(
                        f'GRANT SELECT,INSERT,UPDATE,DELETE ON public."{name}" TO memory_app'
                    )
                )
                db.execute(
                    text(
                        f'REVOKE ALL ON public."{name}" FROM anon,authenticated,service_role,PUBLIC'
                    )
                )
            report["after"] = identity_digest(db)
            assert report["before"] == report["after"], "Canonical identities changed"
            report["revision"] = db.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            report["forced_rls"] = all(
                db.execute(
                    text(
                        "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=CAST(:name AS regclass)"
                    ),
                    {"name": "public." + name},
                ).scalar_one()
                for name in ("continuity_snapshots", "agent_turns")
            )
            assert report["forced_rls"]
        report["status"] = "passed"
        Path("docs/runtime-upgrade-results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report))
    except Exception as error:
        print(
            "Hosted upgrade rolled back or failed: "
            + type(error).__name__
            + "; credentials suppressed"
        )
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
