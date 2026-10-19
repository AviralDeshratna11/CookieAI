from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

from database.tables import metadata


def make_engine(url: str):
    options = {}
    if url == "sqlite://":
        options = {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    engine = create_engine(url, pool_pre_ping=True, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def create_test_schema(engine):
    """Tests only. Deployment uses Alembic, never implicit API startup DDL."""
    from database.registry import register_tables

    register_tables()
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        metadata.create_all(connection)
