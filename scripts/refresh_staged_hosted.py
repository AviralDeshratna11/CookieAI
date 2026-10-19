"""Refresh the untouched staged migration, refusing any changed destination data."""

import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, select, text

from apps.cli.check_hosted import validate_url
from database.registry import register_tables
from database.tables import metadata
from memory.config import Settings
from scripts.migrate_hosted import fingerprint


def main():
    register_tables()
    path = Path("docs/supabase-migration-results.json")
    baseline = json.loads(path.read_text())
    settings = Settings()
    values = dotenv_values(".env.supabase")
    source = create_engine(settings.migration_database_url or settings.database_url)
    target = create_engine(validate_url(values["MEMORY_HOSTED_MIGRATION_DATABASE_URL"]))
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    try:
        with (
            source.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as local,
            target.begin() as remote,
        ):
            remote.execute(text("SET LOCAL search_path TO public,extensions"))
            names = [
                remote.dialect.identifier_preparer.quote(t.name)
                for t in metadata.sorted_tables
            ]
            # Exclusive locks prevent a writer changing the staged copy between
            # the fingerprint guard and replacement. No managed schemas touched.
            remote.exec_driver_sql("SET LOCAL lock_timeout='15s'")
            remote.exec_driver_sql(
                "LOCK TABLE "
                + ",".join("public." + n for n in names)
                + " IN ACCESS EXCLUSIVE MODE"
            )
            revision = local.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if (
                revision != baseline["revision"]
                or remote.execute(
                    text("SELECT version_num FROM public.alembic_version")
                ).scalar_one()
                != revision
            ):
                raise ValueError("Migration revisions differ")
            for table in metadata.sorted_tables:
                staged = remote.execute(select(table)).mappings().all()
                previous = baseline["tables"][table.name]
                if (
                    len(staged) != previous["rows"]
                    or fingerprint(staged) != previous["sha256"]
                ):
                    raise ValueError(
                        "Destination changed; refusing to overwrite " + table.name
                    )
            remote.exec_driver_sql(
                "TRUNCATE TABLE " + ",".join("public." + n for n in names)
            )
            for table in metadata.sorted_tables:
                rows = local.execute(select(table)).mappings().all()
                for start in range(0, len(rows), 200):
                    remote.execute(
                        table.insert(), [dict(r) for r in rows[start : start + 200]]
                    )
                copied = remote.execute(select(table)).mappings().all()
                digest = fingerprint(rows)
                if len(copied) != len(rows) or fingerprint(copied) != digest:
                    raise ValueError("Copy verification failed for " + table.name)
                report["tables"][table.name] = {"rows": len(rows), "sha256": digest}
                print("Verified " + table.name, flush=True)
            report.update(
                revision=revision,
                verified_all_table_fingerprints=True,
                refreshed_staged_snapshot=True,
            )
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Refreshed all " + str(len(report["tables"])) + " tables.")
    except Exception as error:
        print(
            "Refresh failed: "
            + type(error).__name__
            + "; database transaction rolled back. Credentials were not printed."
        )
        raise SystemExit(1) from None
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    main()
