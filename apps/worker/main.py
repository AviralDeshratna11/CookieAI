"""Persistent worker and bounded periodic maintenance. Run as a separately provisioned service agent."""

import logging
import os
import time

from database.engine import make_engine
from memory.config import Settings
from memory.schemas import RequestContext
from memory.service import MemoryService
from models.providers import CompatibleEmbedding, CompatibleExtractor, HashEmbedding
from workers.runtime import Worker


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    settings = Settings()
    embedder = (
        HashEmbedding(settings.embedding_dimensions)
        if settings.embedding_backend == "hash-test"
        else CompatibleEmbedding(settings)
    )
    memory = MemoryService(
        make_engine(settings.database_url),
        embedder,
        CompatibleExtractor(settings),
        settings,
    )
    ctx = RequestContext.model_validate_json(os.environ["MEMORY_WORKER_CONTEXT"])
    worker = Worker(memory, ctx)
    import redis

    from workers.dispatcher import EventDispatcher
    from workers.events import OutboxPublisher, RedisEventBus

    connection = redis.Redis.from_url(
        os.environ.get("MEMORY_REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    publisher = OutboxPublisher(memory.engine, RedisEventBus(connection), ctx)
    dispatcher = EventDispatcher(connection, memory, ctx)
    last = {}
    schedules = {
        "memory.reflect": 600,
        "memory.consolidate": 86400,
        "memory.decay": 86400,
        "DREAMER": 604800,
        "memory.serendipity": 3600,
    }
    while True:
        publisher.flush()
        dispatcher.dispatch()
        now = time.time()
        for queue, interval in schedules.items():
            bucket = int(now // interval)
            if last.get(queue) != bucket:
                worker.queue.enqueue(
                    ctx, queue, {}, f"{ctx.namespace_id}:{queue}:{bucket}"
                )
                last[queue] = bucket
        if not worker.run_once():
            time.sleep(1)


if __name__ == "__main__":
    main()
