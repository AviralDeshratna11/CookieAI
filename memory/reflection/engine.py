"""Incremental event features -> candidate association -> independent counterexample/critic gates."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, insert, select, update

from database import reflection_tables as r
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.provenance.policy import evidence_policy
from memory.schemas import Memory, MemoryCreate, utcnow
from memory.security.auth import NotFound, require_scope

SENSITIVE_TERMS = {
    "religion",
    "ethnicity",
    "sexual_orientation",
    "mental_health",
    "political_affiliation",
    "medical_diagnosis",
}


def feature_projection(repo, episode):
    combinations = {}
    for attempt in episode.attempts:
        description = json.dumps(
            {"tool": attempt.tool, "parameters": attempt.parameters},
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(description) > 2000:
            continue
        combinations.setdefault(description, []).append(attempt.success)
    for description, successes in combinations.items():
        digest = hashlib.sha256(description.encode()).hexdigest()
        repo.db.execute(
            insert(r.features).values(
                namespace_id=repo.ctx.namespace_id,
                episode_id=episode.episode_id,
                feature_hash=digest,
                description=description,
                failure=not all(successes),
                created_at=utcnow(),
            )
        )


class CounterexampleFinder:
    def find(self, repo, feature_hash):
        rows = repo.db.execute(
            select(r.features).where(
                r.features.c.namespace_id == repo.ctx.namespace_id,
                r.features.c.feature_hash == feature_hash,
            )
        ).mappings()
        support, counter = [], []
        for row in rows:
            try:
                episode_memory = repo.get(row["episode_id"])
            except NotFound:
                continue
            if episode_memory.status.value != "ACTIVE":
                continue
            (support if row["failure"] else counter).append(row["episode_id"])
        return list(set(support)), list(set(counter))


class InsightCritic:
    """Separate conservative validator. Rejects weak, circular or sensitive evidence."""

    def judge(self, description, support, counter, evidence):
        if any(term in description.casefold() for term in SENSITIVE_TERMS):
            return "REJECTED"
        if len(set(support)) != len(support) or set(support) & set(counter):
            return "REJECTED"
        if len(support) < 3 or any(not memory.provenance_ids for memory in evidence):
            return "WEAK"
        if len(counter) >= len(support):
            return "DISPUTED"
        if len(support) / (len(support) + len(counter) + 3) < 0.65:
            return "WEAK"
        return "VALIDATED"


class ReflectionEngine:
    def __init__(self, memory, critic=None):
        self.memory = memory
        self.critic = critic or InsightCritic()
        self.counterexamples = CounterexampleFinder()

    @require_scope("write")
    def run(self, ctx, max_features=100):
        reviews = {}
        snapshots = []
        if self.memory.settings.reflection_backend == "compatible":
            # Read evidence, release the transaction, then call the model. Expensive
            # reasoning must not hold the namespace write lock or a job row lock.
            with self.memory.engine.begin() as db:
                repo = SQLMemoryRepository(db, ctx)
                previous = db.execute(
                    select(r.jobs.c.cursor_time)
                    .where(
                        r.jobs.c.namespace_id == ctx.namespace_id,
                        r.jobs.c.payload["stage"].as_string().is_(None)
                        | (r.jobs.c.payload["stage"].as_string() == "statistical"),
                    )
                    .order_by(r.jobs.c.cursor_time.desc())
                    .limit(1)
                ).scalar()
                cursor = previous or datetime(1970, 1, 1, tzinfo=timezone.utc)
                features = list(
                    db.execute(
                        select(r.features)
                        .where(
                            r.features.c.namespace_id == ctx.namespace_id,
                            r.features.c.created_at > cursor,
                        )
                        .order_by(r.features.c.created_at)
                        .limit(max_features)
                    ).mappings()
                )
                for key in dict.fromkeys(row["feature_hash"] for row in features):
                    support, counter = self.counterexamples.find(repo, key)
                    if len(support) < self.memory.policy(repo).minimum_support:
                        continue
                    feature = next(
                        row for row in features if row["feature_hash"] == key
                    )
                    evidence = [repo.get(item) for item in support + counter]
                    snapshots.append(
                        (key, feature["description"], support, counter, evidence)
                    )
                    if (
                        len(snapshots)
                        >= self.memory.settings.reflection_max_model_candidates
                    ):
                        break
            from models.reflection import CompatibleReflection

            for key, description, support, counter, evidence in snapshots:
                reviews[key] = (
                    CompatibleReflection(self.memory.settings).review(
                        description, support, counter, evidence
                    ),
                    {(item.memory_id, item.revision) for item in evidence},
                )
        results = self._run(ctx, max_features, reviews)
        if self.memory.settings.general_discovery_enabled:
            from memory.reflection.discovery import DiscoveryEngine

            results.extend(DiscoveryEngine(self.memory).run(ctx))
        return results

    def _run(self, ctx, max_features, reviews):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            policy = self.memory.policy(repo)
            previous = connection.execute(
                select(r.jobs.c.cursor_time)
                .where(
                    r.jobs.c.namespace_id == ctx.namespace_id,
                    r.jobs.c.payload["stage"].as_string().is_(None)
                    | (r.jobs.c.payload["stage"].as_string() == "statistical"),
                )
                .order_by(r.jobs.c.cursor_time.desc())
                .limit(1)
            ).scalar()
            if previous and previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            cursor = previous or datetime(1970, 1, 1, tzinfo=timezone.utc)
            changed = list(
                connection.execute(
                    select(r.features)
                    .where(
                        r.features.c.namespace_id == ctx.namespace_id,
                        r.features.c.created_at > cursor,
                    )
                    .order_by(r.features.c.created_at)
                    .limit(max_features)
                ).mappings()
            )
            results = []
            model_candidates = 0
            processed_features = set()
            for feature_hash in dict.fromkeys(row["feature_hash"] for row in changed):
                if (
                    self.memory.settings.reflection_backend == "compatible"
                    and model_candidates
                    >= self.memory.settings.reflection_max_model_candidates
                ):
                    break
                feature = next(
                    row for row in changed if row["feature_hash"] == feature_hash
                )
                support, counter = self.counterexamples.find(repo, feature_hash)
                if len(support) < policy.minimum_support:
                    processed_features.add(feature_hash)
                    continue
                ids = support + counter
                evidence = [repo.get(item) for item in ids]
                verdict = self.critic.judge(
                    feature["description"], support, counter, evidence
                )
                review = {}
                if (
                    self.memory.settings.reflection_backend == "compatible"
                    and model_candidates
                    < self.memory.settings.reflection_max_model_candidates
                ):
                    if feature_hash not in reviews:
                        break
                    (proposal, critique, review), reviewed_revisions = reviews[
                        feature_hash
                    ]
                    if reviewed_revisions != {
                        (item.memory_id, item.revision) for item in evidence
                    }:
                        break  # New/corrected/deleted evidence needs another fresh review.
                    review.update(
                        proposal=proposal.model_dump(mode="json"),
                        critique=critique.model_dump(),
                    )
                    normalized_statement = proposal.statement.casefold().replace(
                        " ", "_"
                    )
                    if any(term in normalized_statement for term in SENSITIVE_TERMS):
                        processed_features.add(feature_hash)
                        model_candidates += 1
                        continue
                    # The model can lower a deterministic verdict, never increase it.
                    severity = {"VALIDATED": 0, "WEAK": 1, "DISPUTED": 2, "REJECTED": 3}
                    verdict = max((verdict, critique.verdict), key=severity.get)
                    model_candidates += 1
                processed_features.add(feature_hash)
                if verdict == "REJECTED":
                    continue
                confidence = len(support) / (len(support) + len(counter) + 3)
                status = {
                    "VALIDATED": "ACTIVE",
                    "WEAK": "CANDIDATE",
                    "DISPUTED": "DISPUTED",
                }[verdict]
                statement = f"Observed association: {feature['description']} had failures in {len(support)} episode(s), with {len(counter)} successful counterexample(s). This is correlation, not causation."
                existing = (
                    connection.execute(
                        select(r.insights)
                        .where(
                            r.insights.c.namespace_id == ctx.namespace_id,
                            r.insights.c.feature_hash == feature_hash,
                        )
                        .order_by(r.insights.c.id)
                    )
                    .mappings()
                    .first()
                )
                if existing:
                    old = repo.get(existing["id"])
                    values = old.model_dump()
                    values.update(
                        text=statement,
                        canonical_text=statement,
                        content_hash=hashlib.sha256(statement.encode()).hexdigest(),
                        semantic_hash=hashlib.sha256(
                            statement.casefold().encode()
                        ).hexdigest(),
                        provenance_ids=ids,
                        truth_confidence=confidence,
                        status="ACTIVE" if status == "ACTIVE" else "DISPUTED",
                        expires_at=None
                        if status == "ACTIVE"
                        else utcnow()
                        + timedelta(days=self.memory.settings.candidate_retention_days),
                        revision=old.revision + 1,
                        updated_at=utcnow(),
                        **evidence_policy(evidence),
                    )
                    memory = Memory.model_validate(values)
                    repo.save(memory, self.memory.vector(statement), "UPDATED")
                    connection.execute(
                        delete(t.provenance).where(
                            t.provenance.c.child_id == memory.memory_id
                        )
                    )
                    for parent_id in ids:
                        connection.execute(
                            insert(t.provenance).values(
                                parent_id=parent_id,
                                child_id=memory.memory_id,
                                namespace_id=ctx.namespace_id,
                                kind="DERIVED_FROM",
                            )
                        )
                    connection.execute(
                        delete(r.insight_evidence).where(
                            r.insight_evidence.c.insight_id == memory.memory_id
                        )
                    )
                    connection.execute(
                        delete(r.insight_counterexamples).where(
                            r.insight_counterexamples.c.insight_id == memory.memory_id
                        )
                    )
                else:
                    memory = self.memory._create(
                        repo,
                        MemoryCreate(
                            text=statement,
                            type="INSIGHT",
                            epistemic_type="CORRELATED",
                            source_type="DERIVED",
                            provenance_ids=ids,
                            truth_confidence=confidence,
                            expires_at=None
                            if status == "ACTIVE"
                            else utcnow()
                            + timedelta(
                                days=self.memory.settings.candidate_retention_days
                            ),
                            **evidence_policy(evidence),
                        ),
                    )
                    if status != "ACTIVE":
                        values = memory.model_dump()
                        values.update(status="DISPUTED", revision=memory.revision + 1)
                        memory = Memory.model_validate(values)
                        repo.save(memory, self.memory.vector(statement), "DISPUTED")
                payload = {
                    "insight_id": str(memory.memory_id),
                    "statement": statement,
                    "type": "FAILURE_PATTERN",
                    "epistemic_type": "CORRELATED",
                    "supporting_episode_ids": list(map(str, support)),
                    "counterexample_episode_ids": list(map(str, counter)),
                    "support_count": len(support),
                    "counterexample_count": len(counter),
                    "truth_confidence": confidence,
                    "causality_status": "NONE",
                    "status": status,
                    "critic_verdict": verdict,
                    "last_validated": utcnow().isoformat(),
                    "derivation": "STATISTICAL_AND_LLM" if review else "STATISTICAL",
                    "model_review": review,
                    "population_count": len(support) + len(counter),
                    "confidence_basis": "support / (support + counterexamples + 3); heuristic, not a calibrated probability",
                    "causal": False,
                    "baseline_comparison": "not established; a within-feature association only",
                    "first_detected": existing["payload"].get(
                        "first_detected", memory.created_at.isoformat()
                    )
                    if existing
                    else memory.created_at.isoformat(),
                    "owner_id": str(memory.owner_id),
                    "namespace_id": str(ctx.namespace_id),
                    "privacy_class": memory.privacy_class,
                    "allowed_agent_ids": list(map(str, memory.allowed_agent_ids)),
                    "allowed_project_ids": list(map(str, memory.allowed_project_ids)),
                    "provenance_ids": list(map(str, memory.provenance_ids)),
                    "feature_definition": feature["description"],
                    "independence_basis": "Distinct recorded episodes; producer event independence is not inferred from unique IDs alone",
                    "applicability_conditions": review.get("proposal", {}).get(
                        "applicability_conditions", [feature["description"]]
                    ),
                    "alternative_explanations": review.get("proposal", {}).get(
                        "alternative_explanations", []
                    ),
                    "utility": memory.future_utility,
                    "novelty": memory.novelty,
                    "retention_policy": "Retain for contextual retrieval; decay can make dormant; evidence deletion cascades",
                    "review_policy": "Re-evaluate on changed feature evidence and scheduled reflection",
                }
                if existing:
                    connection.execute(
                        update(r.insights)
                        .where(r.insights.c.id == memory.memory_id)
                        .values(payload=payload)
                    )
                else:
                    connection.execute(
                        insert(r.insights).values(
                            id=memory.memory_id,
                            namespace_id=ctx.namespace_id,
                            feature_hash=feature_hash,
                            payload=payload,
                        )
                    )
                for item in support:
                    connection.execute(
                        insert(r.insight_evidence).values(
                            insight_id=memory.memory_id, episode_id=item
                        )
                    )
                for item in counter:
                    connection.execute(
                        insert(r.insight_counterexamples).values(
                            insight_id=memory.memory_id, episode_id=item
                        )
                    )
                if status == "ACTIVE":
                    from memory.goals.prospective import from_insight

                    from_insight(
                        self.memory, repo, memory, payload, feature["description"]
                    )
                results.append(payload)
            end_cursor = cursor
            for item in changed:
                if item["feature_hash"] not in processed_features:
                    break
                end_cursor = item["created_at"]
            connection.execute(
                insert(r.jobs).values(
                    id=uuid4(),
                    namespace_id=ctx.namespace_id,
                    cursor_time=end_cursor,
                    payload={
                        "stage": "statistical",
                        "features_processed": len(changed),
                        "insights": len(results),
                    },
                )
            )
            return results

    @require_scope("read")
    def list(self, ctx, include_candidates=False):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            result = []
            for row in connection.execute(
                select(r.insights).where(r.insights.c.namespace_id == ctx.namespace_id)
            ):
                try:
                    canonical = repo.get(row.id)
                except NotFound:
                    continue
                if canonical.expires_at and canonical.expires_at <= utcnow():
                    continue
                if include_candidates or row.payload["status"] in {
                    "ACTIVE",
                    "DISPUTED",
                }:
                    payload = dict(row.payload)
                    if (
                        canonical.status.value != "ACTIVE"
                        and payload["status"] == "ACTIVE"
                    ):
                        payload.update(status="DISPUTED", requires_revalidation=True)
                    result.append(payload)
            return result
