"""Back up hosted public application tables using the local PostgreSQL 17 tools."""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


def main():
    url = make_url(
        dotenv_values(".env.supabase")["MEMORY_HOSTED_MIGRATION_DATABASE_URL"]
    )
    env = dict(
        os.environ,
        PGHOST=url.host,
        PGPORT=str(url.port or 5432),
        PGUSER=url.username,
        PGPASSWORD=url.password,
        PGDATABASE=url.database,
        PGSSLMODE="require",
    )
    stamp = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    remote = "/tmp/hosted-" + stamp + ".dump"
    destination = Path("backups") / ("hosted-" + stamp + ".dump")
    destination.parent.mkdir(exist_ok=True)
    command = ["docker", "compose", "exec", "-T"]
    for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE"):
        command.extend(["-e", key])
    try:
        subprocess.run(
            [
                *command,
                "postgres",
                "pg_dump",
                "--schema=public",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                remote,
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["docker", "compose", "cp", "postgres:" + remote, str(destination)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "--list",
                remote,
            ],
            check=True,
            capture_output=True,
        )
        report = {
            "backup": destination.name,
            "bytes": destination.stat().st_size,
            "archive_list_verified": True,
            "encrypted": False,
            "scope": "Hosted public application schema; excludes managed auth/storage",
        }
        Path("docs/hosted-backup-results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report))
    except Exception as error:
        print(
            "Hosted backup failed: "
            + type(error).__name__
            + "; credentials were not printed."
        )
        raise SystemExit(1) from None
    finally:
        subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "rm", "-f", remote],
            capture_output=True,
        )


if __name__ == "__main__":
    main()
