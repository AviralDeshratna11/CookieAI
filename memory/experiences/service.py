from datetime import datetime
from uuid import UUID

from sqlalchemy import insert, select

from database import experience_tables as x
from database import learning_tables as l
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.episodes.service import Episode, EpisodeService
from memory.provenance.policy import evidence_policy
from memory.schemas import Field, MemoryCreate, Score, StrictModel
from memory.security.auth import NotFound, require_scope

FINGERPRINT_FIELDS = (
    "goal_type",
    "domain",
    "error_category",
    "environment",
    "workflow_stage",
)


def fingerprint(episode):
    return {
        **{
            key: episode.context.get(key, "").strip().casefold()
            for key in FINGERPRINT_FIELDS
        },
        "tools": sorted({attempt.tool.casefold() for attempt in episode.attempts}),
        "entities": sorted(episode.context.get("entities", "").casefold().split(",")),
        "outcome": episode.outcome.casefold(),
    }


def structural_similarity(left, right):
    weights = {
        "goal_type": 0.2,
        "domain": 0.1,
        "error_category": 0.3,
        "environment": 0.1,
        "workflow_stage": 0.15,
        "tools": 0.15,
    }
    score = 0
    total = 0
    for key, weight in weights.items():
        if not left.get(key) or not right.get(key):
            continue
        total += weight
        if key == "tools":
            a, b = set(left[key]), set(right[key])
            score += weight * len(a & b) / max(1, len(a | b))
        elif left[key] == right[key]:
            score += weight
    # Missing dimensions reduce confidence; a single generic shared field is insufficient.
    return score if total else 0


class Experience(StrictModel):
    experience_id: UUID
    description: str
    context_signature: dict
    problem_pattern: str
    actions_attempted: list[str]
    successful_actions: list[str]
    failed_actions: list[str]
    outcome_pattern: str
    applicability_conditions: list[str]
    exceptions: list[str]
    source_episode_ids: list[UUID]
    confidence: Score
    success_count: int
    failure_count: int
    first_observed: datetime
    last_observed: datetime


class ExperienceQuery(StrictModel):
    context_signature: dict = Field(default_factory=dict)
    query: str = Field(default="", max_length=4000)
    top_k: int = Field(default=10, ge=1, le=100)
    minimum_similarity: Score = 0.3


class CompileRequest(StrictModel):
    episode_ids: list[UUID] = Field(min_length=1, max_length=100)


class ExperienceService:
    def __init__(self, memory):
        self.memory = memory
        self.episodes = EpisodeService(memory)

    @require_scope("write")
    def compile(self, ctx, episode_ids):
        episode_ids = list(dict.fromkeys(episode_ids))
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            evidence = [repo.get(item) for item in episode_ids]
            episodes = []
            for item in episode_ids:
                row = connection.execute(
                    select(l.episodes.c.payload).where(l.episodes.c.id == item)
                ).first()
                if not row:
                    raise NotFound("episode not found")
                episodes.append(Episode.model_validate(row.payload))
            signatures = [fingerprint(episode) for episode in episodes]
            if len({episode.evidence_origin for episode in episodes}) != 1:
                raise ValueError(
                    "Real, synthetic and rehearsal experience must remain separate"
                )
            if any(
                structural_similarity(signatures[0], signature) < 0.3
                for signature in signatures[1:]
            ):
                raise ValueError(
                    "episodes are not structurally similar enough to generalize"
                )
            attempted = list(
                dict.fromkeys(
                    a.action for episode in episodes for a in episode.attempts
                )
            )
            successful = list(
                dict.fromkeys(
                    a.action
                    for episode in episodes
                    for a in episode.attempts
                    if a.success
                )
            )
            failed = list(
                dict.fromkeys(
                    a.action
                    for episode in episodes
                    for a in episode.attempts
                    if not a.success
                )
            )
            successes = sum(
                episode.outcome.casefold() == "success" for episode in episodes
            )
            failures = len(episodes) - successes
            description = f"Past experience in {signatures[0].get('error_category') or signatures[0].get('domain') or 'recorded context'}: "
            description += f"successful prior actions {successful}; failed prior actions {failed}. "
            description += (
                f"Observed in {len(episodes)} episode(s); applicability is conditional."
            )
            canonical = self.memory._create(
                repo,
                MemoryCreate(
                    text=description,
                    type="SEMANTIC",
                    epistemic_type="INFERRED",
                    source_type="DERIVED",
                    provenance_ids=episode_ids,
                    truth_confidence=min(0.8, len(episodes) / (len(episodes) + 3)),
                    **evidence_policy(evidence),
                ),
            )
            result = Experience(
                experience_id=canonical.memory_id,
                description=description,
                context_signature=signatures[0],
                problem_pattern=signatures[0].get("error_category")
                or episodes[0].trigger,
                actions_attempted=attempted,
                successful_actions=successful,
                failed_actions=failed,
                outcome_pattern=f"{successes} success; {failures} non-success",
                applicability_conditions=[
                    f"{key}={value}"
                    for key, value in signatures[0].items()
                    if value and key != "outcome"
                ],
                exceptions=[
                    episode.title
                    for episode in episodes
                    if episode.outcome.casefold() != "success"
                ],
                source_episode_ids=episode_ids,
                confidence=canonical.truth_confidence,
                success_count=successes,
                failure_count=failures,
                first_observed=min(episode.start_time for episode in episodes),
                last_observed=max(episode.end_time for episode in episodes),
            )
            if not connection.execute(
                select(x.experiences.c.id).where(
                    x.experiences.c.id == result.experience_id
                )
            ).first():
                connection.execute(
                    insert(x.experiences).values(
                        id=result.experience_id, payload=result.model_dump(mode="json")
                    )
                )
                for episode_id in episode_ids:
                    connection.execute(
                        insert(x.experience_episodes).values(
                            experience_id=result.experience_id, episode_id=episode_id
                        )
                    )
            return result

    @require_scope("read")
    def get(self, ctx, experience_id):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.get(experience_id)
            row = connection.execute(
                select(x.experiences.c.payload).where(
                    x.experiences.c.id == experience_id
                )
            ).first()
            if not row:
                raise NotFound("experience not found")
            return Experience.model_validate(row.payload)

    @require_scope("read")
    def search(self, ctx, request):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            result = []
            rows = connection.execute(
                select(x.experiences.c.payload)
                .join(t.memories, t.memories.c.id == x.experiences.c.id)
                .where(t.memories.c.namespace_id == ctx.namespace_id)
            ).all()
            permitted = repo.get_many(
                [UUID(row.payload["experience_id"]) for row in rows], strict=False
            )
            for row in rows:
                experience = Experience.model_validate(row.payload)
                memory = permitted.get(experience.experience_id)
                if memory is None:
                    continue
                if memory.status.value not in {"ACTIVE", "DISPUTED"}:
                    continue
                similarity = structural_similarity(
                    experience.context_signature, request.context_signature
                )
                if similarity >= request.minimum_similarity:
                    result.append(
                        {
                            "experience": experience.model_dump(mode="json"),
                            "similarity": similarity,
                            "epistemic_type": "INFERRED",
                        }
                    )
            return sorted(result, key=lambda item: -item["similarity"])[: request.top_k]
