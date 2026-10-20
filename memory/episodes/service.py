from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import insert, select

from database import learning_tables as l
from database.repositories.memory import SQLMemoryRepository
from memory.schemas import Field, MemoryCreate, Score, StrictModel, utcnow
from memory.security.auth import NotFound, require_scope


class ToolAttempt(StrictModel):
    observation_id: UUID | None = None
    sequence: int | None = Field(default=None, ge=0, le=1000)
    tool: str = Field(min_length=1, max_length=200)
    intent: str = Field(min_length=1, max_length=2000)
    action: str = Field(min_length=1, max_length=2000)
    parameters: dict = Field(default_factory=dict)
    result: str = Field(default="", max_length=8000)
    latency_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    error: str | None = Field(default=None, max_length=4000)
    retry: int = Field(default=0, ge=0)
    success: bool
    failure_reason: str | None = Field(default=None, max_length=2000)


class EpisodeInput(StrictModel):
    evidence_origin: Literal["REAL", "SYNTHETIC", "REHEARSAL"] = "REAL"
    event_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    trigger: str = Field(min_length=1, max_length=1000)
    goal: str = Field(min_length=1, max_length=1000)
    context: dict[str, str] = Field(default_factory=dict, max_length=30)
    attempts: list[ToolAttempt] = Field(default_factory=list, max_length=30)
    linked_memory_ids: list[UUID] = Field(default_factory=list, max_length=100)
    outcome: str = Field(default="unknown", max_length=2000)
    resolution: str | None = Field(default=None, max_length=2000)
    start_time: datetime = Field(default_factory=utcnow)
    end_time: datetime = Field(default_factory=utcnow)
    importance: Score = 0.5


class Episode(EpisodeInput):
    episode_id: UUID
    confidence: Score = 0.5
    created_at: datetime = Field(default_factory=utcnow)


class TaskPartition(StrictModel):
    groups: list[list[UUID]] = Field(min_length=1, max_length=30)


class EpisodeService:
    def __init__(self, memory_service):
        self.memory = memory_service

    def _save(self, repo, body):
        if body.event_id:
            from database import tables as foundation
            from memory.security.auth import Conflict

            matches = repo.db.execute(
                select(l.episodes.c.payload)
                .join(foundation.memories, foundation.memories.c.id == l.episodes.c.id)
                .where(
                    foundation.memories.c.namespace_id == repo.ctx.namespace_id,
                    foundation.memories.c.payload["source_id"].as_string()
                    == str(body.event_id),
                )
            ).scalars()
            for payload in matches:
                previous = Episode.model_validate(payload)
                repo.get(previous.episode_id)
                excluded = {
                    "start_time",
                    "end_time",
                    "episode_id",
                    "confidence",
                    "created_at",
                    "linked_memory_ids",
                }
                if previous.model_dump(exclude=excluded) != body.model_dump(
                    exclude=excluded
                ):
                    raise Conflict("event identity was reused with different content")
                return previous
        for value in (body.start_time, body.end_time):
            MemoryCreate.aware_time(value)
        if body.end_time < body.start_time:
            raise ValueError("episode end precedes start")
        source_ids = list(body.linked_memory_ids)
        for memory_id in source_ids:
            repo.get(memory_id)
        from memory.provenance.policy import evidence_policy

        policy = evidence_policy([repo.get(item) for item in source_ids])
        source_policy = {**policy}
        if source_ids:
            source_policy.update(
                source_type="DERIVED",
                provenance_ids=list(source_ids),
                epistemic_type="INFERRED",
            )
        else:
            source_policy.update(source_type="TOOL", epistemic_type="OBSERVED")
        for attempt in body.attempts:
            # Each tool attempt is an explicit supplied observation, never an invented model event.
            source = self.memory._create(
                repo,
                MemoryCreate(
                    text=attempt.model_dump_json(),
                    type="OBSERVATION",
                    **source_policy,
                    observed_at=body.end_time,
                    importance=body.importance,
                ),
            )
            source_ids.append(source.memory_id)
        if not source_ids:
            raise ValueError("episode requires actual atomic observations")
        # Capture caller-supplied event metadata as an attributed observation as well.
        metadata_source = self.memory._create(
            repo,
            MemoryCreate(
                text=body.model_dump_json(exclude={"attempts", "linked_memory_ids"}),
                type="OBSERVATION",
                **source_policy,
                observed_at=body.end_time,
            ),
        )
        source_ids.append(metadata_source.memory_id)
        evidence = [repo.get(memory_id) for memory_id in source_ids]
        allowed = None
        projects = []
        privacy = {"PUBLIC": 0, "NORMAL": 1, "PRIVATE": 2, "HIGHLY_PRIVATE": 3}
        for memory in evidence:
            if memory.allowed_agent_ids:
                allowed = (
                    set(memory.allowed_agent_ids)
                    if allowed is None
                    else allowed & set(memory.allowed_agent_ids)
                )
            if memory.allowed_project_ids:
                projects = list(memory.allowed_project_ids)
        if allowed is not None and not allowed:
            raise ValueError("episode evidence has no common agent authorization")
        category = max((memory.privacy_class for memory in evidence), key=privacy.get)
        # Canonical summary is deterministic and never generalized into a universal rule.
        summary = f"Episode: {body.title}. Goal: {body.goal}. Outcome: {body.outcome}. "
        summary += " ".join(
            f"Attempt {a.action}: {'succeeded' if a.success else 'failed'}."
            for a in body.attempts
        )
        memory = self.memory._create(
            repo,
            MemoryCreate(
                text=summary,
                type="EPISODIC",
                source_id=body.event_id,
                epistemic_type="INFERRED",
                source_type="DERIVED",
                provenance_ids=source_ids,
                allowed_agent_ids=list(allowed or []),
                allowed_project_ids=projects,
                privacy_class=category,
                observed_at=body.end_time,
                event_at=body.start_time,
                importance=body.importance,
            ),
        )
        episode = Episode(
            **body.model_dump(exclude={"linked_memory_ids"}),
            linked_memory_ids=source_ids,
            episode_id=memory.memory_id,
        )
        existing = repo.db.execute(
            select(l.episodes.c.id).where(l.episodes.c.id == episode.episode_id)
        ).first()
        if not existing:
            repo.db.execute(
                insert(l.episodes).values(
                    id=episode.episode_id, payload=episode.model_dump(mode="json")
                )
            )
            for source_id in source_ids:
                repo.db.execute(
                    insert(l.episode_memories).values(
                        episode_id=episode.episode_id, memory_id=source_id
                    )
                )
            from memory.reflection.engine import feature_projection

            feature_projection(repo, episode)
        return episode

    @require_scope("write")
    def record(self, ctx, body):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            repo.session()
            return self._save(repo, body)

    @require_scope("read")
    def get(self, ctx, episode_id):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.get(episode_id)
            row = connection.execute(
                select(l.episodes.c.payload).where(l.episodes.c.id == episode_id)
            ).first()
            if not row:
                raise NotFound("episode not found")
            return Episode.model_validate(row.payload)

    @require_scope("read")
    def search(self, ctx, request):
        hits = self.memory.search(ctx, request)
        episodes = []
        for hit in hits:
            if hit.memory.type.value == "EPISODIC":
                episodes.append(
                    {
                        "episode": self.get(ctx, hit.memory.memory_id).model_dump(
                            mode="json"
                        ),
                        "relevance": hit.relevance,
                    }
                )
        return episodes

    @require_scope("read")
    def get_many(self, ctx, identities):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            permitted = repo.get_many(identities, strict=False)
            return [
                Episode.model_validate(payload).model_dump(mode="json")
                for payload in db.execute(
                    select(l.episodes.c.payload).where(l.episodes.c.id.in_(permitted))
                ).scalars()
            ]

    @require_scope("write")
    def segment(self, ctx, memory_ids, gap_minutes=30):
        memories = sorted(
            [self.memory.get(ctx, item) for item in memory_ids],
            key=lambda m: m.observed_at,
        )
        groups = []

        def task(item):
            return tuple(tag for tag in item.tags if tag.startswith("task:"))

        for memory in memories:
            if (
                not groups
                or memory.source_session_id != groups[-1][-1].source_session_id
                or (memory.observed_at - groups[-1][-1].observed_at).total_seconds()
                > gap_minutes * 60
                or "episode-boundary" in memory.tags
                or task(memory) != task(groups[-1][-1])
            ):
                groups.append([])
            groups[-1].append(memory)
        result = []
        if self.memory.settings.reflection_backend == "compatible":
            from models.reflection import CompatibleReflection

            refined = []
            for group in groups:
                if len(group) < 3 or len(group) > 30:
                    refined.append(group)
                    continue
                proposal = CompatibleReflection(self.memory.settings).structured(
                    "episode_segmenter",
                    TaskPartition,
                    {
                        "task": "Partition chronological observations into contiguous task segments. Return every source ID exactly once in order. Split only at a meaningful goal or task change. Never invent actions, outcomes or source IDs.",
                        "observations": [
                            {"id": str(m.memory_id), "text": m.text[:1200]}
                            for m in group
                        ],
                    },
                    self.memory.settings.reflection_model
                    or self.memory.settings.extraction_model,
                )
                flattened = [identity for part in proposal.groups for identity in part]
                if any(not part for part in proposal.groups) or flattened != [
                    m.memory_id for m in group
                ]:
                    raise ValueError(
                        "segmenter must preserve every source exactly once in chronological order"
                    )
                by_id = {m.memory_id: m for m in group}
                refined.extend(
                    [[by_id[identity] for identity in part] for part in proposal.groups]
                )
            groups = refined
        for group in groups:
            result.append(
                self.record(
                    ctx,
                    EpisodeInput(
                        event_id=uuid5(
                            NAMESPACE_URL,
                            "memory-segment:"
                            + ":".join(str(m.memory_id) for m in group),
                        ),
                        title=group[0].canonical_text[:500],
                        trigger="interaction segment",
                        goal="retain completed interaction context",
                        linked_memory_ids=[m.memory_id for m in group],
                        start_time=group[0].observed_at,
                        end_time=group[-1].observed_at,
                    ),
                )
            )
        return result
