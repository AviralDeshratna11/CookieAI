"""Reproducible lexical fixture. This is not a production-model semantic benchmark."""

import json
import statistics
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import insert

from database import tables as t
from database.engine import create_test_schema, make_engine
from memory.config import Settings
from memory.evaluation import ranking_metrics
from memory.schemas import Extraction, MemoryCreate, RequestContext, SearchRequest
from memory.service import MemoryService
from models.providers import HashEmbedding


def run():
    engine = make_engine("sqlite://")
    create_test_schema(engine)
    ctx = RequestContext(
        user_id=uuid4(),
        requesting_agent_id=uuid4(),
        namespace_id=uuid4(),
        session_id=uuid4(),
        purpose="synthetic evaluation",
        requested_scope="write",
    )
    with engine.begin() as db:
        db.execute(insert(t.users).values(id=ctx.user_id))
        db.execute(
            insert(t.agents).values(id=ctx.requesting_agent_id, user_id=ctx.user_id)
        )
        db.execute(
            insert(t.namespaces).values(id=ctx.namespace_id, owner_id=ctx.user_id)
        )
        db.execute(
            insert(t.grants).values(
                namespace_id=ctx.namespace_id,
                agent_id=ctx.requesting_agent_id,
                can_read=True,
                can_write=True,
                can_delete=True,
            )
        )

    class Extractor:
        def extract(self, context):
            return Extraction()

    memory = MemoryService(
        engine, HashEmbedding(), Extractor(), Settings(_env_file=None)
    )
    items = []
    for index in range(100):
        items.append(
            memory.create(
                ctx,
                MemoryCreate(
                    text=f"Project Code{index:04d} selected database{index:04d}"
                ),
            )
        )
    records = []
    latency = []
    for index in range(20):
        start = time.perf_counter()
        hits = memory.search(
            ctx,
            SearchRequest(
                query=f"Code{index:04d} database{index:04d}", top_k=5, score_threshold=0
            ),
        )
        latency.append((time.perf_counter() - start) * 1000)
        records.append(
            ranking_metrics(
                [hit.memory.memory_id for hit in hits], [items[index].memory_id], 5
            )
        )
    return {
        "fixture": "100 deterministic lexical records; 20 exact-identifier queries; hash-test embeddings",
        "metrics": {
            key: statistics.mean(row[key] for row in records) for key in records[0]
        },
        "latency_ms": {
            "median": statistics.median(latency),
            "p95": sorted(latency)[int(0.95 * (len(latency) - 1))],
        },
    }


if __name__ == "__main__":
    report = run()
    Path("docs/benchmark-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
