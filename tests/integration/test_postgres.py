"""Real PostgreSQL tests use an isolated schema, never drop a user's database."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import RecordingExtractor, provision
from sqlalchemy import create_engine, text

from memory.config import Settings
from memory.schemas import MemoryCreate, SearchRequest
from memory.service import MemoryService
from models.providers import HashEmbedding

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres(ctx, monkeypatch):
    url = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "set MEMORY_TEST_DATABASE_URL to execute the PostgreSQL acceptance gate"
        )
    schema = "test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as db:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    # A generated hexadecimal identifier, never user SQL, controls the test schema.
    from sqlalchemy.engine import make_url

    scoped_url = make_url(url).update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    )
    monkeypatch.setenv(
        "MEMORY_DATABASE_URL", scoped_url.render_as_string(hide_password=False)
    )
    monkeypatch.setenv(
        "MEMORY_MIGRATION_DATABASE_URL",
        scoped_url.render_as_string(hide_password=False),
    )
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(scoped_url)
    provision(engine, ctx)
    yield engine
    engine.dispose()
    with admin.begin() as db:
        db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def test_real_pgvector_migration_transactions_and_concurrent_dedup(postgres, ctx):
    service = MemoryService(
        postgres, HashEmbedding(), RecordingExtractor(), Settings(_env_file=None)
    )

    def create(_):
        return service.create(
            ctx, MemoryCreate(text="Alpha PostgreSQL database")
        ).memory_id

    with ThreadPoolExecutor(max_workers=4) as executor:
        memory_ids = list(executor.map(create, range(8)))
    assert len(set(memory_ids)) == 1
    assert (
        service.search(ctx, SearchRequest(query="Alpha PostgreSQL", score_threshold=0))[
            0
        ].memory.memory_id
        == memory_ids[0]
    )
    with postgres.connect() as db:
        assert db.execute(text("SELECT count(*) FROM memory_mutations")).scalar() == 1
        assert (
            db.execute(
                text("SELECT vector_dims(vector) FROM memory_embeddings")
            ).scalar()
            == 64
        )
        assert (
            db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0012"
        )
    service.delete(ctx, memory_ids[0])
    assert (
        service.search(ctx, SearchRequest(query="Alpha PostgreSQL", score_threshold=0))
        == []
    )


def test_real_postgres_model_failure_rolls_back(postgres, ctx):
    class FailingEmbedding(HashEmbedding):
        def embed(self, text):
            raise RuntimeError("failure")

    service = MemoryService(
        postgres, FailingEmbedding(), RecordingExtractor(), Settings(_env_file=None)
    )
    with pytest.raises(RuntimeError):
        service.create(ctx, MemoryCreate(text="Rollback"))
    with postgres.connect() as db:
        assert db.execute(text("SELECT count(*) FROM memories")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM sessions")).scalar() == 0


def test_non_superuser_rls_isolation(postgres, ctx):
    from database.repositories.memory import SQLMemoryRepository

    service = MemoryService(
        postgres, HashEmbedding(), RecordingExtractor(), Settings(_env_file=None)
    )
    memory = service.create(ctx, MemoryCreate(text="RLS protected"))
    role = "test_role_" + uuid4().hex
    with postgres.begin() as db:
        schema = db.execute(text("SELECT current_schema()")).scalar()
        db.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
        db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
        db.execute(
            text(
                f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'
            )
        )
    try:
        with postgres.begin() as db:
            db.execute(text(f'SET LOCAL ROLE "{role}"'))
            assert db.execute(text("SELECT count(*) FROM memories")).scalar() == 0
            repo = SQLMemoryRepository(db, ctx)
            assert repo.get(memory.memory_id).memory_id == memory.memory_id
            db.execute(
                text("SELECT set_config('memory.namespace_id',:other,true)"),
                {"other": str(uuid4())},
            )
            assert db.execute(text("SELECT count(*) FROM memories")).scalar() == 0
            assert (
                db.execute(text("SELECT count(*) FROM memory_embeddings")).scalar() == 0
            )
    finally:
        with postgres.begin() as db:
            db.execute(text(f'DROP OWNED BY "{role}"'))
            db.execute(text(f'DROP ROLE "{role}"'))
