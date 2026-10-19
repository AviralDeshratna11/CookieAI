"""Local pg_dump and restore drill. Backups contain private data and are Git-ignored."""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def docker(*args, capture=False):
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", *args],
        check=True,
        capture_output=capture,
        text=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-drill", action="store_true")
    args = parser.parse_args()
    stamp = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    root = Path("backups").resolve()
    root.mkdir(exist_ok=True)
    path = root / ("memory-" + stamp + ".dump")
    remote = "/tmp/memory-" + stamp + ".dump"
    docker("pg_dump", "-U", "memory", "-d", "memory", "-Fc", "-f", remote)
    subprocess.run(
        ["docker", "compose", "cp", "postgres:" + remote, str(path)], check=True
    )
    report = {"backup": path.name, "bytes": path.stat().st_size, "encrypted": False}
    if args.restore_drill:
        # A fresh database only; never restore over the live database.
        target = "memory_restore_" + uuid4().hex
        docker("createdb", "-U", "memory", target)
        docker(
            "pg_restore",
            "-U",
            "memory",
            "--no-owner",
            "--exit-on-error",
            "-d",
            target,
            remote,
        )
        sql = "SELECT count(*) FROM memories;"
        source_count = docker(
            "psql", "-U", "memory", "-d", "memory", "-Atc", sql, capture=True
        ).stdout.strip()
        restored_count = docker(
            "psql", "-U", "memory", "-d", target, "-Atc", sql, capture=True
        ).stdout.strip()
        report.update(
            restore_database=target,
            restored_memory_count=int(restored_count),
            source_memory_count=int(source_count),
            count_matches=source_count == restored_count,
        )
        assert source_count == restored_count, (
            "Database changed during backup or restore is incomplete"
        )
    docker("rm", "-f", remote)
    Path("docs/backup-drill-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
