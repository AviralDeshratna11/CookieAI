"""Read-only hosted PostgreSQL preflight; never prints credentials or connection URLs."""

import argparse
import json
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def validate_url(value):
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Hosted database must be PostgreSQL")
    if url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise ValueError("Hosted connections must require TLS")
    if url.port == 6543:
        raise ValueError(
            "Use a direct or session-pooler endpoint, not the transaction pooler, for this preflight"
        )
    return url.set(drivername="postgresql+psycopg")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.supabase"))
    args = parser.parse_args()
    if not args.env_file.exists():
        raise SystemExit("Hosted connection settings have not been configured yet.")
    values = dotenv_values(args.env_file)
    names = ("MEMORY_HOSTED_DATABASE_URL", "MEMORY_HOSTED_MIGRATION_DATABASE_URL")
    if any(not values.get(name) for name in names):
        raise SystemExit(
            "Both restricted application and migration connection URLs are required."
        )
    try:
        urls = {name: validate_url(values[name]) for name in names}
    except Exception as error:
        raise SystemExit(
            "Invalid hosted connection settings ("
            + type(error).__name__
            + "); credentials were not printed."
        ) from None
    if (urls[names[0]].host, urls[names[0]].database) != (
        urls[names[1]].host,
        urls[names[1]].database,
    ):
        raise SystemExit(
            "Application and migration endpoints must identify the same database host and name."
        )
    result = {}
    for name, url in urls.items():
        engine = create_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": 15}
        )
        try:
            with engine.connect() as db:
                role = db.execute(
                    text(
                        "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    )
                ).one()
                # With Supavisor, pg_stat_ssl describes the pooler's upstream
                # connection, not this client's TLS session. Inspect libpq.
                tls = db.connection.driver_connection.pgconn.ssl_in_use
                vector = db.execute(
                    text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                ).scalar()
                if not tls:
                    raise ValueError("Database session is not using TLS")
                if name == names[0] and (role.rolsuper or role.rolbypassrls):
                    raise ValueError(
                        "Application role must not be superuser or bypass RLS"
                    )
                result["application" if name == names[0] else "migration"] = {
                    "connected": True,
                    "tls": bool(tls),
                    "superuser": role.rolsuper,
                    "bypass_rls": role.rolbypassrls,
                    "pgvector_version": vector,
                }
        except Exception as error:
            raise SystemExit(
                "Hosted preflight failed ("
                + type(error).__name__
                + "); credentials were not printed."
            ) from None
        finally:
            engine.dispose()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
