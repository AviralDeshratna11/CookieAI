from uuid import uuid4

import pytest
from sqlalchemy import insert

from database import tables as t
from database.engine import create_test_schema, make_engine
from memory.config import Settings
from memory.schemas import RequestContext
from memory.service import MemoryService
from models.providers import HashEmbedding


class RecordingExtractor:
    def __init__(self, response=None, error=None):
        from memory.schemas import Extraction

        self.response = response or Extraction()
        self.error = error
        self.contexts = []

    def extract(self, context):
        self.contexts.append(context)
        if self.error:
            raise self.error
        return self.response


def provision(engine, ctx, read=True, write=True, delete=True):
    with engine.begin() as db:
        db.execute(insert(t.users).values(id=ctx.user_id))
        db.execute(
            insert(t.agents).values(id=ctx.requesting_agent_id, user_id=ctx.user_id)
        )
        db.execute(
            insert(t.namespaces).values(
                id=ctx.namespace_id, owner_id=ctx.user_id, kind="USER_PRIVATE"
            )
        )
        db.execute(
            insert(t.grants).values(
                namespace_id=ctx.namespace_id,
                agent_id=ctx.requesting_agent_id,
                can_read=read,
                can_write=write,
                can_delete=delete,
            )
        )


@pytest.fixture
def ctx():
    return RequestContext(
        user_id=uuid4(),
        requesting_agent_id=uuid4(),
        namespace_id=uuid4(),
        session_id=uuid4(),
        purpose="integration testing",
        requested_scope="write",
    )


@pytest.fixture
def engine(ctx):
    engine = make_engine("sqlite://")
    create_test_schema(engine)
    provision(engine, ctx)
    yield engine
    engine.dispose()


@pytest.fixture
def extractor():
    return RecordingExtractor()


@pytest.fixture
def service(engine, extractor):
    return MemoryService(engine, HashEmbedding(), extractor, Settings(_env_file=None))
