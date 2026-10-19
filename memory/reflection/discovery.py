"""Bounded LLM-assisted discovery beyond tool features, using the existing insight store."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update

from database import reflection_tables as r
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.insights.lifecycle import seal, structural_key
from memory.provenance.policy import evidence_policy
from memory.reflection.engine import SENSITIVE_TERMS
from memory.schemas import Field, Memory, MemoryCreate, StrictModel, utcnow
from memory.security.auth import NotFound, require_scope
from models.reflection import CompatibleReflection, Critique


class Discovery(StrictModel):
    statement: str = Field(min_length=1, max_length=1500)
    type: Literal[
        "RECURRING_PATTERN",
        "SUCCESS_PATTERN",
        "FAILURE_PATTERN",
        "TEMPORAL_PATTERN",
        "STRATEGY",
        "ANALOGY",
        "DEPENDENCY",
        "ANOMALY",
    ]
    supporting_memory_ids: list[UUID] = Field(min_length=3, max_length=20)
    applicability_conditions: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(min_length=1, max_length=10)


class Discoveries(StrictModel):
    patterns: list[Discovery] = Field(default_factory=list, max_length=1)


class Counterevidence(StrictModel):
    counterexample_memory_ids: list[UUID] = Field(default_factory=list, max_length=20)
    alternative_explanations: list[str] = Field(min_length=1, max_length=10)


class Reassessment(StrictModel):
    supporting_memory_ids: list[UUID] = Field(default_factory=list, max_length=20)


class DiscoveryEngine:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def run(self, ctx):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            cursor = db.execute(
                select(r.jobs.c.cursor_time)
                .where(
                    r.jobs.c.namespace_id == ctx.namespace_id,
                    r.jobs.c.payload["stage"].as_string() == "general",
                )
                .order_by(r.jobs.c.cursor_time.desc())
                .limit(1)
            ).scalar()
            cursor = cursor or datetime(1970, 1, 1, tzinfo=timezone.utc)
            if cursor.tzinfo is None:
                cursor = cursor.replace(tzinfo=timezone.utc)
            # Derived output is never recycled into independent source support.
            evidence = [
                item
                for item in repo.recent(limit=100)
                if item.source_type != "DERIVED"
                and item.source_type != "TOOL"
                and not item.provenance_ids
                and item.status.value == "ACTIVE"
                and repo.valid_at(item)
            ]
            existing_rows = (
                db.execute(
                    select(r.insights)
                    .where(r.insights.c.namespace_id == ctx.namespace_id)
                    .order_by(r.insights.c.id)
                    .limit(100)
                )
                .mappings()
                .all()
            )
            digest = hashlib.sha256(
                repr(sorted((str(m.memory_id), m.revision) for m in evidence)).encode()
            ).hexdigest()
            pending_reviews = [
                row
                for row in existing_rows
                if row["payload"].get("derivation") == "LLM_AND_RULES"
                and row["payload"].get("input_digest") != digest
            ]
            selected = pending_reviews[0] if pending_reviews else None
            if selected:
                for identity in selected["payload"].get(
                    "supporting_memory_ids", []
                ) + selected["payload"].get("counterexample_memory_ids", []):
                    try:
                        item = repo.get(UUID(identity))
                    except NotFound:
                        continue
                    if (
                        item.status.value == "ACTIVE"
                        and repo.valid_at(item)
                        and not item.provenance_ids
                        and item.source_type not in {"DERIVED", "TOOL"}
                        and item.memory_id not in {m.memory_id for m in evidence}
                    ):
                        evidence.insert(0, item)
            changed = [item for item in evidence if item.updated_at > cursor]
        if not changed and not selected:
            return []
        end_cursor = max((item.updated_at for item in changed), default=cursor)
        adapter = CompatibleReflection(self.memory.settings)
        model = (
            self.memory.settings.reflection_model
            or self.memory.settings.extraction_model
        )
        critic_model = self.memory.settings.critic_model or model
        source_map = {item.memory_id: item for item in evidence[:60]}
        samples = [
            {
                "id": str(item.memory_id),
                "text": item.text[:1200],
                "session_id": str(item.source_session_id),
                "observed_at": item.observed_at.isoformat(),
            }
            for item in source_map.values()
        ]
        proposals = Discoveries()
        if selected:
            prior = selected["payload"]
            reassessment = adapter.structured(
                "reflection_agent",
                Reassessment,
                {
                    "candidate": prior,
                    "available_evidence": samples,
                    "task": "Reassess this existing claim. Return only IDs of current directly supporting evidence, including new support. Exclude changed, superseded, merely related, duplicate and contrary evidence. Return an empty list if unsupported.",
                },
                model,
            )
            proposals = (
                Discoveries(
                    patterns=[
                        Discovery(
                            statement=prior["statement"],
                            type=prior["type"],
                            supporting_memory_ids=reassessment.supporting_memory_ids,
                            applicability_conditions=prior.get(
                                "applicability_conditions", []
                            ),
                            limitations=prior.get(
                                "limitations", ["Bounded evidence coverage."]
                            ),
                        )
                    ]
                )
                if len(reassessment.supporting_memory_ids) >= 3
                else Discoveries()
            )
            if not proposals.patterns:
                with self.memory.engine.begin() as db:
                    repo = SQLMemoryRepository(db, ctx)
                    repo.lock_namespace()
                    old = repo.get(selected["id"])
                    values = old.model_dump()
                    values.update(
                        status="DISPUTED",
                        revision=old.revision + 1,
                        updated_at=utcnow(),
                        truth_confidence=0,
                    )
                    repo.save(
                        Memory.model_validate(values),
                        self.memory.vector(old.text),
                        "DISPUTED",
                    )
                    payload = seal(
                        {
                            **prior,
                            "status": "INVALIDATED",
                            "truth_confidence": 0,
                            "input_digest": digest,
                        },
                        [],
                        prior,
                    )
                    db.execute(
                        update(r.insights)
                        .where(r.insights.c.id == old.memory_id)
                        .values(payload=payload)
                    )
                    self.memory._invalidate_descendants(repo, old.memory_id)
                return [payload]
        elif len({item.source_session_id for item in source_map.values()}) >= 3:
            proposals = adapter.structured(
                "reflection_agent",
                Discoveries,
                {
                    "evidence": samples,
                    "task": "Look for repeated preferences, constraints, decisions, successes, failures, sequences, temporal regularities, dependencies or useful analogies. Return patterns=[] if unrelated or weak. Every pattern needs three directly supporting source IDs from independent sessions. Do not infer sensitive traits, invent events, or claim causality.",
                },
                model,
            )
        reviewed = []
        for proposal in proposals.patterns:
            ids = proposal.supporting_memory_ids
            if len(set(ids)) != len(ids) or not set(ids).issubset(source_map):
                raise ValueError("discovery cited duplicate or unknown evidence")
            if any(
                term in proposal.statement.casefold().replace(" ", "_")
                for term in SENSITIVE_TERMS
            ):
                continue
            support = [source_map[item] for item in ids]
            from memory.reflection.structured import independent

            if len(independent(support)) != len(support):
                continue
            sessions = {item.source_session_id for item in support}
            if len(sessions) < 3:
                continue
            counter = adapter.structured(
                "counterexample_finder",
                Counterevidence,
                {
                    "candidate": proposal.model_dump(mode="json"),
                    "available_evidence": samples,
                    "task": "Find contrary source records and alternative explanations. Cite only available IDs outside the support set. State limited search coverage.",
                },
                critic_model,
            )
            counter_ids = counter.counterexample_memory_ids
            if (
                len(set(counter_ids)) != len(counter_ids)
                or set(counter_ids) & set(ids)
                or not set(counter_ids).issubset(source_map)
            ):
                raise ValueError("counterexample finder cited invalid evidence")
            critique = adapter.structured(
                "insight_critic",
                Critique,
                {
                    "candidate": proposal.model_dump(mode="json"),
                    "counterevidence": counter.model_dump(mode="json"),
                    "evidence": samples,
                    "task": "Try to falsify the pattern. Reject unsupported claims, duplicates, confounding and sensitive inferences. A small sample is WEAK.",
                },
                critic_model,
            )
            reviewed.append((proposal, counter, critique, support))
        results = []
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            for proposal, counter, critique, support in reviewed:
                ids = proposal.supporting_memory_ids + counter.counterexample_memory_ids
                current = []
                for identity in ids:
                    try:
                        item = repo.get(identity)
                    except NotFound:
                        break
                    if (
                        item.status.value != "ACTIVE"
                        or item.revision != source_map[identity].revision
                    ):
                        break
                    current.append(item)
                if len(current) != len(ids):
                    # Do not advance the cursor past evidence that changed mid-review.
                    return []
                roots = len({item.source_session_id for item in support})
                counter_roots = len(
                    independent(
                        [
                            source_map[identity]
                            for identity in counter.counterexample_memory_ids
                        ]
                    )
                )
                confidence = roots / (roots + counter_roots + 3)
                active = confidence >= 0.65 and critique.verdict == "VALIDATED"
                key = structural_key(
                    proposal.type, proposal.statement, proposal.applicability_conditions
                )
                existing = (
                    selected
                    or db.execute(
                        select(r.insights).where(
                            r.insights.c.namespace_id == ctx.namespace_id,
                            r.insights.c.feature_hash == key,
                        )
                    )
                    .mappings()
                    .first()
                )
                prior = existing["payload"] if existing else {}
                if prior.get("input_digest") == digest:
                    continue
                status = (
                    "REJECTED"
                    if critique.verdict == "REJECTED"
                    else "DISPUTED"
                    if critique.verdict == "DISPUTED"
                    or len(counter.counterexample_memory_ids) >= roots
                    else "ACTIVE"
                    if active
                    else "CANDIDATE"
                )
                active = status == "ACTIVE"
                if existing:
                    old = repo.get(existing["id"])
                    values = old.model_dump()
                    values.update(
                        provenance_ids=ids,
                        truth_confidence=confidence,
                        status="ACTIVE" if active else "DISPUTED",
                        revision=old.revision + 1,
                        updated_at=utcnow(),
                        expires_at=None
                        if active
                        else utcnow()
                        + timedelta(days=self.memory.settings.candidate_retention_days),
                        **evidence_policy([*current, old]),
                    )
                    memory = Memory.model_validate(values)
                    repo.save(memory, self.memory.vector(memory.text), "UPDATED")
                    db.execute(
                        delete(t.provenance).where(
                            t.provenance.c.child_id == memory.memory_id,
                            t.provenance.c.kind == "DERIVED_FROM",
                        )
                    )
                    for identity in ids:
                        db.execute(
                            insert(t.provenance).values(
                                parent_id=identity,
                                child_id=memory.memory_id,
                                namespace_id=ctx.namespace_id,
                                kind="DERIVED_FROM",
                            )
                        )
                    self.memory._invalidate_descendants(repo, memory.memory_id)
                else:
                    memory = self.memory._create(
                        repo,
                        MemoryCreate(
                            text=proposal.statement,
                            type="INSIGHT",
                            epistemic_type="INFERRED",
                            source_type="DERIVED",
                            provenance_ids=ids,
                            truth_confidence=confidence,
                            expires_at=None
                            if active
                            else utcnow()
                            + timedelta(
                                days=self.memory.settings.candidate_retention_days
                            ),
                            **evidence_policy(current),
                        ),
                    )
                    if not active:
                        values = memory.model_dump()
                        values.update(status="DISPUTED", revision=memory.revision + 1)
                        memory = Memory.model_validate(values)
                        repo.save(memory, self.memory.vector(memory.text), "DISPUTED")
                finding = {
                    "insight_id": str(memory.memory_id),
                    "statement": proposal.statement,
                    "type": proposal.type,
                    "epistemic_type": "INFERRED",
                    "status": status,
                    "supporting_memory_ids": list(
                        map(str, proposal.supporting_memory_ids)
                    ),
                    "counterexample_memory_ids": list(
                        map(str, counter.counterexample_memory_ids)
                    ),
                    "support_count": roots,
                    "counterexample_count": len(counter.counterexample_memory_ids),
                    "truth_confidence": confidence,
                    "causality_status": "NONE",
                    "causal": False,
                    "applicability_conditions": proposal.applicability_conditions,
                    "limitations": proposal.limitations,
                    "alternative_explanations": counter.alternative_explanations,
                    "critic_verdict": critique.verdict,
                    "critic_reason": critique.reason,
                    "last_validated": utcnow().isoformat(),
                    "derivation": "LLM_AND_RULES",
                    "model_review": {
                        "generator_model": model,
                        "critic_model": critic_model,
                        "critic_independence": "separate invocation"
                        if model == critic_model
                        else "separate model",
                    },
                    "search_coverage": "At most 60 authorized recent direct source memories; absence of counterexamples is not proof",
                }
                finding = seal({**finding, "input_digest": digest}, current, prior)
                if existing:
                    db.execute(
                        update(r.insights)
                        .where(r.insights.c.id == memory.memory_id)
                        .values(payload=finding, feature_hash=key)
                    )
                else:
                    db.execute(
                        insert(r.insights).values(
                            id=memory.memory_id,
                            namespace_id=ctx.namespace_id,
                            feature_hash=key,
                            payload=finding,
                        )
                    )
                if active and proposal.applicability_conditions:
                    import json

                    from memory.goals.prospective import from_insight

                    from_insight(
                        self.memory,
                        repo,
                        memory,
                        finding,
                        json.dumps({"context": proposal.applicability_conditions[0]}),
                    )
                results.append(finding)
            db.execute(
                insert(r.jobs).values(
                    id=uuid4(),
                    namespace_id=ctx.namespace_id,
                    cursor_time=cursor if selected else end_cursor,
                    payload={
                        "stage": "general",
                        "source_count": len(samples),
                        "insights": len(results),
                        "proposals_reviewed": len(reviewed),
                        "critic_verdicts": [item[2].verdict for item in reviewed],
                    },
                )
            )
        return results
