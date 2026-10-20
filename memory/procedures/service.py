from collections import Counter
from datetime import datetime
from uuid import UUID

from sqlalchemy import insert, select, update

from database import experience_tables as x
from database import learning_tables as learning
from database import procedure_tables as p
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.episodes.service import Episode
from memory.experiences.service import (
    Experience,
    ExperienceQuery,
    structural_similarity,
)
from memory.provenance.policy import evidence_policy
from memory.schemas import Field, Memory, MemoryCreate, Score, StrictModel, utcnow
from memory.security.auth import NotFound, require_scope


class ProcedureCompile(StrictModel):
    experience_ids: list[UUID] = Field(min_length=1, max_length=100)
    confirmation_memory_id: UUID | None = None


class Procedure(StrictModel):
    procedure_id: UUID
    name: str
    goal: str
    applicability_conditions: list[str]
    preconditions: list[str]
    steps: list[str]
    tools: list[str]
    expected_result: str
    known_failure_modes: list[str]
    recovery_steps: list[str]
    source_episode_ids: list[UUID]
    source_experience_ids: list[UUID]
    context_signature: dict
    success_count: int
    failure_count: int
    confidence: Score
    last_used: datetime | None = None
    last_successful_use: datetime | None = None


class ProcedureFeedback(StrictModel):
    success: bool
    evidence_memory_id: UUID


class ProcedureService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def compile(self, ctx, request):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            ids = list(dict.fromkeys(request.experience_ids))
            evidence = [repo.get(item) for item in ids]
            experiences = []
            for item in ids:
                row = connection.execute(
                    select(x.experiences.c.payload).where(x.experiences.c.id == item)
                ).first()
                if not row:
                    raise NotFound("experience not found")
                experiences.append(Experience.model_validate(row.payload))
            episodes = sorted(
                {
                    item
                    for experience in experiences
                    for item in experience.source_episode_ids
                },
                key=str,
            )
            if request.confirmation_memory_id:
                confirmation = repo.get(request.confirmation_memory_id)
                if (
                    confirmation.epistemic_type.value != "USER_STATED"
                    or confirmation.predicate != "confirms_procedure"
                ):
                    raise ValueError(
                        "procedure confirmation must be an attributed explicit user statement"
                    )
                if confirmation.object != str(ids[0]):
                    raise ValueError(
                        "confirmation must identify this source experience"
                    )
                evidence.append(confirmation)
                ids.append(confirmation.memory_id)
            elif len(episodes) < 3:
                raise ValueError(
                    "learned procedure requires at least three independent episodes"
                )
            observed = []
            producers = set()
            for identity in episodes:
                repo.get(identity)
                payload = connection.execute(
                    select(learning.episodes.c.payload).where(
                        learning.episodes.c.id == identity
                    )
                ).scalar_one()
                episode = Episode.model_validate(payload)
                if episode.evidence_origin != "REAL":
                    raise ValueError(
                        "Synthetic and rehearsal episodes cannot activate real-world procedures"
                    )
                producer = episode.event_id or episode.episode_id
                if producer not in producers:
                    producers.add(producer)
                    observed.append(episode)
            sequences = Counter(
                tuple(a.action for a in e.attempts if a.success)
                for e in observed
                if e.outcome.casefold() == "success"
                and any(a.success for a in e.attempts)
            )
            if not sequences:
                raise ValueError("no observed successful strategy")
            sequence, repeated = sequences.most_common(1)[0]
            if not request.confirmation_memory_id and repeated < 3:
                raise ValueError(
                    "ordered procedure requires three matching observed successful sequences"
                )
            steps = list(sequence)
            successes = sum(e.outcome.casefold() == "success" for e in observed)
            failures = len(observed) - successes
            recoveries = list(
                dict.fromkeys(
                    a.action
                    for e in observed
                    for index, a in enumerate(e.attempts)
                    if a.success
                    and any(not previous.success for previous in e.attempts[:index])
                )
            )
            confidence = min(0.9, (successes + 1) / (successes + failures + 3))
            memory = self.memory._create(
                repo,
                MemoryCreate(
                    text="Conditional procedure: "
                    + "; ".join(steps)
                    + f". Based on {len(episodes)} observed episodes, not a universal rule.",
                    type="PROCEDURAL",
                    epistemic_type="INFERRED",
                    source_type="DERIVED",
                    provenance_ids=ids,
                    truth_confidence=confidence,
                    **evidence_policy(evidence),
                ),
            )
            result = Procedure(
                procedure_id=memory.memory_id,
                name=experiences[0].problem_pattern,
                goal="reuse a previously successful conditional strategy",
                applicability_conditions=experiences[0].applicability_conditions,
                preconditions=experiences[0].applicability_conditions,
                steps=steps,
                tools=experiences[0].context_signature.get("tools", []),
                expected_result="historically observed success under stated conditions",
                known_failure_modes=list(
                    dict.fromkeys(
                        a
                        for experience in experiences
                        for a in experience.failed_actions
                    )
                ),
                recovery_steps=recoveries,
                source_episode_ids=episodes,
                source_experience_ids=request.experience_ids,
                context_signature=experiences[0].context_signature,
                success_count=successes,
                failure_count=failures,
                confidence=confidence,
            )
            if not connection.execute(
                select(p.procedures.c.id).where(
                    p.procedures.c.id == result.procedure_id
                )
            ).first():
                connection.execute(
                    insert(p.procedures).values(
                        id=result.procedure_id, payload=result.model_dump(mode="json")
                    )
                )
                for item in set(request.experience_ids):
                    connection.execute(
                        insert(p.procedure_experiences).values(
                            procedure_id=result.procedure_id, experience_id=item
                        )
                    )
            return result

    @require_scope("read")
    def get(self, ctx, procedure_id):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.get(procedure_id)
            row = connection.execute(
                select(p.procedures.c.payload).where(p.procedures.c.id == procedure_id)
            ).first()
            if not row:
                raise NotFound("procedure not found")
            return Procedure.model_validate(row.payload)

    @require_scope("read")
    def search(self, ctx, request: ExperienceQuery):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            results = []
            rows = connection.execute(
                select(p.procedures.c.payload)
                .join(t.memories, t.memories.c.id == p.procedures.c.id)
                .where(t.memories.c.namespace_id == ctx.namespace_id)
            ).all()
            permitted = repo.get_many(
                [UUID(row.payload["procedure_id"]) for row in rows], strict=False
            )
            for row in rows:
                procedure = Procedure.model_validate(row.payload)
                memory = permitted.get(procedure.procedure_id)
                if memory is None:
                    continue
                if memory.status.value != "ACTIVE":
                    continue
                similarity = structural_similarity(
                    procedure.context_signature, request.context_signature
                )
                if similarity >= request.minimum_similarity:
                    results.append(
                        {
                            "procedure": procedure.model_dump(mode="json"),
                            "applicability": similarity,
                        }
                    )
            return sorted(results, key=lambda item: -item["applicability"])[
                : request.top_k
            ]

    @require_scope("write")
    def feedback(self, ctx, procedure_id, body):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            memory = repo.get(procedure_id)
            evidence = repo.get(body.evidence_memory_id)
            if evidence.epistemic_type.value not in {
                "OBSERVED",
                "USER_STATED",
                "VERIFIED",
            }:
                raise ValueError("procedure outcomes require observed evidence")
            row = connection.execute(
                select(p.procedures.c.payload).where(p.procedures.c.id == procedure_id)
            ).first()
            if not row:
                raise NotFound("procedure not found")
            procedure = Procedure.model_validate(row.payload)
            if body.evidence_memory_id in memory.provenance_ids:
                return procedure
            evidence_policy([memory, evidence])
            procedure.success_count += int(body.success)
            procedure.failure_count += int(not body.success)
            procedure.confidence = min(
                0.9,
                (procedure.success_count + 1)
                / (procedure.success_count + procedure.failure_count + 3),
            )
            procedure.last_used = utcnow()
            if body.success:
                procedure.last_successful_use = utcnow()
            values = memory.model_dump()
            values.update(
                provenance_ids=memory.provenance_ids + [body.evidence_memory_id],
                truth_confidence=procedure.confidence,
                revision=memory.revision + 1,
                updated_at=utcnow(),
                successful_use_count=memory.successful_use_count + int(body.success),
            )
            revised = Memory.model_validate(values)
            # Additional evidence may restrict access; never broaden the previous procedure.
            policy = evidence_policy([memory, evidence])
            revised = Memory.model_validate({**revised.model_dump(), **policy})
            repo.save(revised, self.memory.vector(revised.canonical_text), "UPDATED")
            connection.execute(
                insert(t.provenance).values(
                    parent_id=evidence.memory_id,
                    child_id=procedure_id,
                    namespace_id=ctx.namespace_id,
                    kind="DERIVED_FROM",
                )
            )
            connection.execute(
                update(p.procedures)
                .where(p.procedures.c.id == procedure_id)
                .values(payload=procedure.model_dump(mode="json"))
            )
            return procedure
