"""Persistent worker and bounded periodic maintenance. Run as a separately provisioned service agent."""

import logging
import os
import signal
import time
from pathlib import Path
from threading import Event, Thread

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
    ctx = RequestContext.model_validate_json(
        os.environ.get("MEMORY_WORKER_CONTEXT")
        or Path(
            os.environ.get("MEMORY_WORKER_CONTEXT_FILE", "config/worker-context.json")
        ).read_text(encoding="utf-8")
    )
    worker = Worker(memory, ctx)
    import redis

    from workers.dispatcher import EventDispatcher
    from workers.events import OutboxPublisher, RedisEventBus

    connection = redis.Redis.from_url(
        settings.redis_url, socket_timeout=5, socket_connect_timeout=5
    )
    publisher = OutboxPublisher(memory.engine, RedisEventBus(connection), ctx)
    dispatcher = EventDispatcher(connection, memory, ctx)
    last = {}
    schedules = {
        "memory.reflect": settings.reflection_interval_seconds,
        "memory.consolidate": settings.daily_interval_seconds,
        "memory.decay": settings.daily_interval_seconds,
        "DREAMER": settings.dreamer_interval_seconds,
        "memory.serendipity": settings.serendipity_interval_seconds,
    }
    stopping = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopping.set())
    heartbeat = f"memory.worker:{ctx.namespace_id}:{ctx.requesting_agent_id}"

    def keep_alive():
        while not stopping.wait(30):
            try:
                connection.set(heartbeat, str(time.time()), ex=900)
            except Exception as error:
                logging.warning("worker_heartbeat_failed: %s", type(error).__name__)

    health_thread = Thread(target=keep_alive, daemon=True)
    health_thread.start()
    logging.info("worker_started", extra={"agent_id": str(ctx.requesting_agent_id)})
    try:
        while not stopping.is_set():
            try:
                connection.set(heartbeat, str(time.time()), ex=900)
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
                    stopping.wait(1)
            except Exception as error:
                logging.warning("worker_iteration_failed: %s", type(error).__name__)
                stopping.wait(5)
    finally:
        stopping.set()
        health_thread.join(timeout=4)
        connection.delete(heartbeat)
        connection.close()
        logging.info("worker_stopped")


if __name__ == "__main__":
    main()
