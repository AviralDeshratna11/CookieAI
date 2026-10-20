"""Redis event consumer schedules idempotent graph and experience projections."""

from uuid import UUID, uuid4

from redis.exceptions import ResponseError

from memory.security.auth import NotFound
from workers.queue import JobQueue


class EventDispatcher:
    def __init__(self, redis, memory, context):
        self.redis, self.memory, self.ctx = redis, memory, context
        self.queue = JobQueue(memory.engine)
        self.stream = f"memory.events:{context.namespace_id}"
        self.group = "memory-projections"
        self.consumer = "worker-" + uuid4().hex
        try:
            redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def dispatch(self, count=100):
        reclaimed = self.redis.xautoclaim(
            self.stream,
            self.group,
            self.consumer,
            min_idle_time=60000,
            start_id="0-0",
            count=count,
        )
        messages = [(self.stream, reclaimed[1])]
        messages += self.redis.xreadgroup(
            self.group, self.consumer, {self.stream: ">"}, count=count
        )
        processed = 0
        for _, entries in messages:
            for entry_id, raw in entries:
                event = {
                    (key.decode() if isinstance(key, bytes) else key): (
                        value.decode() if isinstance(value, bytes) else value
                    )
                    for key, value in raw.items()
                }
                if event["event_type"] in {
                    "MEMORY_CREATED",
                    "MEMORY_UPDATED",
                    "MEMORY_CORRECTED",
                }:
                    if self.memory.settings.autonomy_enabled:
                        from memory.autonomy.service import TaskSupervisor

                        TaskSupervisor(self.memory).wake(
                            self.ctx, UUID(event["event_id"])
                        )
                    try:
                        memory = self.memory.get(self.ctx, UUID(event["object_id"]))
                    except NotFound:
                        memory = None
                    if memory:
                        self.queue.enqueue(
                            self.ctx,
                            "memory.graph",
                            {"memory_id": str(memory.memory_id)},
                            "graph:" + event["event_id"],
                        )
                        if memory.type.value == "EPISODIC":
                            self.queue.enqueue(
                                self.ctx,
                                "memory.reflect",
                                {},
                                "reflect:" + event["event_id"],
                            )
                            self.queue.enqueue(
                                self.ctx,
                                "memory.experience",
                                {"episode_id": str(memory.memory_id)},
                                "experience:" + event["event_id"],
                            )
                self.redis.xack(self.stream, self.group, entry_id)
                processed += 1
        return processed
