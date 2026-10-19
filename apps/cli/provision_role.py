"""Administrative local role provisioning for an initialized project database."""

from sqlalchemy import text

from database.engine import make_engine
from memory.config import Settings


def main():
    settings = Settings()
    engine = make_engine(settings.migration_database_url or settings.database_url)
    password = settings.app_password.get_secret_value()
    with engine.begin() as db:
        exists = db.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname='memory_app'")
        ).scalar()
        if not exists:
            statement = db.execute(
                text(
                    "SELECT format('CREATE ROLE memory_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',CAST(:password AS text))"
                ),
                {"password": password},
            ).scalar()
            db.exec_driver_sql(statement)
        role = db.execute(
            text(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='memory_app'"
            )
        ).one()
        if role.rolsuper or role.rolbypassrls:
            raise ValueError("memory_app must not bypass row-level security")
        db.execute(text("GRANT USAGE ON SCHEMA public TO memory_app"))
        db.execute(
            text(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO memory_app"
            )
        )
        db.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO memory_app"
            )
        )
    print("Application role provisioned without superuser or RLS bypass.")


if __name__ == "__main__":
    main()
