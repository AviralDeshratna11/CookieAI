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


@pytest.mark.skipif(
    not os.environ.get("MEMORY_LIVE_ACCEPTANCE"),
    reason="opt-in bounded real free-provider acceptance",
)
def test_live_nvidia_assistant_outcome_and_later_procedure(postgres, ctx):
    """Synthetic observations in an isolated local PG schema, real NVIDIA models."""
    import json
    from pathlib import Path
    from uuid import UUID

    from memory.agent.service import AgentService, TurnFeedback, TurnInput
    from memory.context.continuity import ContinuityService
    from memory.episodes.service import EpisodeInput, ToolAttempt
    from memory.experiences.service import ExperienceQuery
    from memory.procedures.service import ProcedureService
    from memory.schemas import RememberRequest
    from models.providers import CompatibleEmbedding, CompatibleExtractor
    from workers.runtime import Worker

    settings = Settings(
        _env_file=(".env", ".env.cloud"),
        context_tokenizer_file="config/nemotron-tokenizer.json",
    )
    service = MemoryService(
        postgres, CompatibleEmbedding(settings), CompatibleExtractor(settings), settings
    )
    remember = RememberRequest.model_validate(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Synthetic project Cedar uses PostgreSQL. Remember this database choice.",
                }
            ],
            "mode": "infer",
            "remember_explicitly": True,
            "idempotency_key": "live-cedar",
        }
    )
    recorded = service.remember(ctx, remember)
    assert recorded and any("PostgreSQL" in m.text for m in recorded)
    agent = AgentService(service)
    fresh = ctx.model_copy(update={"session_id": uuid4()})
    submitted = agent.submit(
        fresh,
        TurnInput(
            message="Which database does synthetic project Cedar use?",
            mode="raw",
            idempotency_key="live-recall",
        ),
    )
    # Execute only the exact submitted job; no other namespace or user's queue is consumed.
    worker = Worker(service, fresh)
    assert worker.run_once()
    first = agent.get(fresh, UUID(submitted["turn_id"]))
    assert first["status"] == "COMPLETED" and "postgresql" in first["answer"].casefold()
    signature = {
        "domain": "synthetic infra",
        "goal_type": "repair",
        "error_category": "certificate",
        "workflow_stage": "recovery",
    }
    for index in range(3):
        outcome = agent.feedback(
            fresh,
            UUID(submitted["turn_id"]),
            TurnFeedback(
                feedback_id=uuid4(),
                episode=EpisodeInput(
                    title=f"Synthetic recovery {index}",
                    trigger="synthetic incident",
                    goal="restore TLS",
                    context=signature,
                    outcome="success",
                    attempts=[
                        ToolAttempt(
                            tool="certbot",
                            intent="restore TLS",
                            action="inspect certificate",
                            success=True,
                        ),
                        ToolAttempt(
                            tool="certbot",
                            intent="restore TLS",
                            action="renew certificate",
                            success=True,
                        ),
                    ],
                ),
            ),
        )
        worker.execute(
            "memory.experience", fresh, {"episode_id": outcome["episode_id"]}
        )
    procedures = ProcedureService(service).search(
        fresh, ExperienceQuery(context_signature=signature)
    )
    assert procedures and procedures[0]["procedure"]["steps"] == [
        "inspect certificate",
        "renew certificate",
    ]
    assert ContinuityService(service).build(fresh)
    later = fresh.model_copy(update={"session_id": uuid4()})
    second = agent.submit(
        later,
        TurnInput(
            message="For a similar certificate incident, what previously observed procedure can I consider?",
            mode="raw",
            context_signature=signature,
            idempotency_key="live-reuse",
        ),
    )
    # The earlier summary/outcome jobs remain durable; execute the exact turn via the worker handler.
    worker.execute("memory.agent_turn", later, {"turn_id": second["turn_id"]})
    result = agent.get(later, UUID(second["turn_id"]))
    assert result["status"] == "COMPLETED"
    assert procedures[0]["procedure"]["procedure_id"] in result["context_memory_ids"]
    report = {
        "kind": "synthetic isolated local PostgreSQL schema with real NVIDIA LLM and embeddings",
        "status": "passed",
        "llm": settings.extraction_model,
        "embedding": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "extraction": True,
        "cross_session_assistant_recall": True,
        "outcome_to_procedure": True,
        "later_assistant_received_procedure": True,
        "continuity_snapshot": True,
        "tokenizer": service.token_counter.mode,
        "not_tested": [
            "production discovery precision",
            "sustained provider outage",
            "hosted database interruption",
        ],
    }
    Path("docs/assistant-live-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


def test_external_migration_transaction_rolls_back_schema_and_data():
    url = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set MEMORY_TEST_DATABASE_URL for the PostgreSQL acceptance gate")
    engine = create_engine(url)
    schema = "test_atomic_" + uuid4().hex
    try:
        with engine.begin() as db:
            db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        with engine.connect() as db:
            transaction = db.begin()
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
            db.execute(text(f'SET LOCAL search_path TO "{schema}",public'))
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = db
            command.upgrade(cfg, "head")
            db.execute(text("INSERT INTO users(id) VALUES (:id)"), {"id": uuid4()})
            assert db.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
            transaction.rollback()
        with engine.connect() as db:
            assert (
                db.execute(
                    text("SELECT 1 FROM pg_namespace WHERE nspname=:schema"),
                    {"schema": schema},
                ).scalar()
                is None
            )
    finally:
        engine.dispose()


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
            == "0017"
        )
    service.delete(ctx, memory_ids[0])
    assert (
        service.search(ctx, SearchRequest(query="Alpha PostgreSQL", score_threshold=0))
        == []
    )


def test_real_2048_dimension_candidate_search(postgres, ctx):
    service = MemoryService(
        postgres,
        HashEmbedding(2048),
        RecordingExtractor(),
        Settings(_env_file=None, embedding_dimensions=2048),
    )
    memory = service.create(
        ctx, MemoryCreate(text="Cloud semantic projection uses PostgreSQL")
    )
    hits = service.search(
        ctx, SearchRequest(query="Cloud semantic projection", score_threshold=0)
    )
    assert hits[0].memory.memory_id == memory.memory_id
    with postgres.connect() as db:
        assert (
            "halfvec"
            in db.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname=current_schema() AND indexname='ix_memory_vectors_2048_hnsw'"
                )
            ).scalar_one()
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
