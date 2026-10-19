"""One-time local-to-hosted copy. Stop writers and take a backup before running."""

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values, set_key
from sqlalchemy import create_engine, select, text

from apps.cli.check_hosted import validate_url
from database.registry import register_tables
from database.tables import metadata
from memory.config import Settings


def fingerprint(rows):
    def encode(value):
        return value.tolist() if hasattr(value, "tolist") else str(value)

    digests = sorted(
        hashlib.sha256(
            json.dumps(dict(row), sort_keys=True, default=encode).encode()
        ).hexdigest()
        for row in rows
    )
    return hashlib.sha256("".join(digests).encode()).hexdigest()


def main():
    register_tables()
    settings = Settings()
    env_path = Path(".env.supabase")
    values = dotenv_values(env_path)
    admin_url = validate_url(values["MEMORY_HOSTED_MIGRATION_DATABASE_URL"])
    source = create_engine(settings.migration_database_url or settings.database_url)
    target = create_engine(admin_url, connect_args={"connect_timeout": 20})
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    password = secrets.token_urlsafe(36)
    app_url = admin_url.set(username="memory_app", password=password)
    try:
        with (
            source.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as local,
            target.begin() as remote,
        ):
            existing = (
                remote.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
                .scalars()
                .all()
            )
            if existing:
                raise ValueError("Destination public schema must be empty")
            if remote.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname='memory_app'")
            ).scalar():
                raise ValueError("Destination memory_app role already exists")
            revision = local.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = remote
            remote.execute(text("SET LOCAL search_path TO public,extensions"))
            command.upgrade(cfg, "head")
            assert (
                remote.execute(
                    text("SELECT version_num FROM public.alembic_version")
                ).scalar_one()
                == revision
            )
            for table in metadata.sorted_tables:
                rows = local.execute(select(table)).mappings().all()
                for start in range(0, len(rows), 200):
                    remote.execute(
                        table.insert(), [dict(r) for r in rows[start : start + 200]]
                    )
                copied = remote.execute(select(table)).mappings().all()
                assert len(copied) == len(rows), table.name
                digest = fingerprint(rows)
                assert fingerprint(copied) == digest, table.name
                report["tables"][table.name] = {"rows": len(rows), "sha256": digest}
            statement = remote.execute(
                text(
                    "SELECT format('CREATE ROLE memory_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',CAST(:password AS text))"
                ),
                {"password": password},
            ).scalar_one()
            remote.exec_driver_sql(statement)
            remote.exec_driver_sql(
                "ALTER ROLE memory_app SET search_path TO public,extensions"
            )
            remote.exec_driver_sql(
                "GRANT USAGE ON SCHEMA public,extensions TO memory_app"
            )
            for name in [*metadata.tables, "alembic_version"]:
                quoted = remote.dialect.identifier_preparer.quote(name)
                remote.exec_driver_sql(
                    f"REVOKE ALL ON TABLE public.{quoted} FROM PUBLIC,anon,authenticated,service_role"
                )
                if name != "alembic_version":
                    remote.exec_driver_sql(
                        f"GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.{quoted} TO memory_app"
                    )
            remote.exec_driver_sql(
                "GRANT SELECT ON TABLE public.alembic_version TO memory_app"
            )
            remote.exec_driver_sql(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon,authenticated,service_role"
            )
            remote.exec_driver_sql(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO memory_app"
            )
            report["revision"] = revision
            report["verified_all_table_fingerprints"] = True
            # Persist the generated credential before commit; never print it.
            set_key(
                env_path,
                "MEMORY_HOSTED_DATABASE_URL",
                app_url.render_as_string(hide_password=False),
            )
        Path("docs/supabase-migration-results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "tables_verified": len(report["tables"]),
                    "revision": revision,
                    "memories": report["tables"]["memories"]["rows"],
                }
            )
        )
    except Exception as error:
        # Database exceptions may contain credential-bearing SQL; suppress traces.
        print(
            "Migration failed: "
            + type(error).__name__
            + "; remote transaction rolled back. Credentials were not printed."
        )
        raise SystemExit(1) from None
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    main()
