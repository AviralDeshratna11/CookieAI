"""Controlled random association. NONE is a normal result; no external actions are executed."""

import hashlib
import random
from datetime import timedelta

from sqlalchemy import insert, select

from database import experience_tables as x
from database import reflection_tables as r
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.experiences.service import Experience, structural_similarity
from memory.provenance.policy import evidence_policy
from memory.reflection.engine import InsightCritic
from memory.schemas import Memory, MemoryCreate, utcnow
from memory.security.auth import NotFound, require_scope


class SerendipityEngine:
    def __init__(self, memory, rng=None, critic=None):
        self.memory = memory
        self.rng = rng or random.Random()
        self.critic = critic or InsightCritic()

    def select_anchor(self, memories):
        if not memories:
            return None
        category = self.rng.choices(
            ["recent", "important", "unresolved", "dormant", "random", "novel"],
            weights=[25, 20, 15, 15, 15, 10],
            k=1,
        )[0]
        if category == "recent":
            pool = sorted(memories, key=lambda m: m.created_at, reverse=True)[:20]
        elif category == "important":
            pool = sorted(memories, key=lambda m: m.importance, reverse=True)[:20]
        elif category == "unresolved":
            pool = [m for m in memories if m.status.value == "DISPUTED"]
        elif category == "dormant":
            pool = [m for m in memories if m.status.value == "DORMANT"]
        elif category == "novel":
            pool = sorted(memories, key=lambda m: m.novelty, reverse=True)[:20]
        else:
            pool = memories
        return self.rng.choice(pool or memories)

    @require_scope("write")
    def run(self, ctx, max_pairs=12):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            policy = self.memory.policy(repo)
            experiences = []
            for row in connection.execute(
                select(x.experiences.c.payload)
                .join(t.memories, t.memories.c.id == x.experiences.c.id)
                .where(t.memories.c.namespace_id == ctx.namespace_id)
                .order_by(t.memories.c.payload["updated_at"].as_string().desc())
                .limit(300)
            ):
                experience = Experience.model_validate(row.payload)
                try:
                    memory = repo.get(experience.experience_id)
                except NotFound:
                    continue
                if memory.status.value in {"ACTIVE", "DORMANT"}:
                    experiences.append((experience, memory))
            if len(experiences) < 2:
                return []
            anchor_memory = self.select_anchor([memory for _, memory in experiences])
            anchor = next(
                exp
                for exp, memory in experiences
                if memory.memory_id == anchor_memory.memory_id
            )
            candidates = [
                pair
                for pair in experiences
                if pair[0].experience_id != anchor.experience_id
            ]
            self.rng.shuffle(candidates)
            # Distant-domain samples complement structurally nearest candidates.
            candidates.sort(
                key=lambda pair: structural_similarity(
                    anchor.context_signature, pair[0].context_signature
                ),
                reverse=True,
            )
            near = candidates[: max(1, max_pairs // 3)]
            temporal = sorted(
                candidates,
                key=lambda pair: abs(
                    (pair[0].last_observed - anchor.last_observed).total_seconds()
                ),
            )[: max(1, max_pairs // 3)]
            distant = [
                pair
                for pair in candidates
                if pair[0].context_signature.get("domain")
                != anchor.context_signature.get("domain")
            ]
            self.rng.shuffle(distant)
            proposals = []
            seen = set()
            for candidate, candidate_memory in (
                near + temporal + distant[: max_pairs - len(near) - len(temporal)]
            ):
                if candidate.experience_id in seen:
                    continue
                seen.add(candidate.experience_id)
                similarity = structural_similarity(
                    anchor.context_signature, candidate.context_signature
                )
                if similarity < 0.65:
                    continue
                shared = set(anchor.successful_actions) & set(
                    candidate.successful_actions
                )
                if not shared:
                    continue  # Frequent NONE, not an interesting-sounding story.
                ids = [anchor.experience_id, candidate.experience_id]
                support = list(
                    set(anchor.source_episode_ids + candidate.source_episode_ids)
                )
                counter = []
                for other, _ in experiences:
                    if other.experience_id in ids:
                        continue
                    if structural_similarity(
                        anchor.context_signature, other.context_signature
                    ) >= 0.65 and shared & set(other.failed_actions):
                        counter.extend(other.source_episode_ids)
                counter = list(set(counter) - set(support))
                episode_evidence = [repo.get(item) for item in support + counter]
                verdict = self.critic.judge(
                    "conditional cross-domain strategy",
                    support,
                    counter,
                    episode_evidence,
                )
                if verdict == "REJECTED":
                    continue
                confidence = min(
                    similarity, len(support) / (len(support) + len(counter) + 3)
                )
                novelty = (
                    0.6
                    if anchor.context_signature.get("domain")
                    != candidate.context_signature.get("domain")
                    else 0.2
                )
                utility = 0.6
                active = (
                    confidence >= policy.serendipity_confidence
                    and novelty >= policy.serendipity_novelty
                    and utility >= policy.serendipity_utility
                    and len(support) >= policy.minimum_support
                    and verdict == "VALIDATED"
                )
                differences = {
                    key: [
                        anchor.context_signature.get(key),
                        candidate.context_signature.get(key),
                    ]
                    for key in anchor.context_signature
                    if anchor.context_signature.get(key)
                    != candidate.context_signature.get(key)
                }
                statement = f"Possible analogy: actions {sorted(shared)} previously succeeded in structurally related contexts. Differences: {differences}. Counterexamples: {len(counter)}. This is not a universal or causal rule."
                key = hashlib.sha256(
                    "|".join(sorted(map(str, ids))).encode()
                ).hexdigest()
                if connection.execute(
                    select(r.insights.c.id).where(
                        r.insights.c.namespace_id == ctx.namespace_id,
                        r.insights.c.feature_hash == key,
                    )
                ).first():
                    continue
                evidence = [anchor_memory, candidate_memory] + [
                    repo.get(item) for item in counter
                ]
                sources = ids + counter
                memory = self.memory._create(
                    repo,
                    MemoryCreate(
                        text=statement,
                        type="INSIGHT",
                        epistemic_type="HYPOTHESIZED",
                        source_type="DERIVED",
                        provenance_ids=sources,
                        truth_confidence=confidence,
                        novelty=novelty,
                        future_utility=utility,
                        expires_at=None
                        if active
                        else utcnow()
                        + timedelta(days=self.memory.settings.candidate_retention_days),
                        **evidence_policy(evidence),
                    ),
                )
                if not active:
                    values = memory.model_dump()
                    values.update(status="DISPUTED", revision=memory.revision + 1)
                    repo.save(
                        Memory.model_validate(values),
                        self.memory.vector(statement),
                        "DISPUTED",
                    )
                payload = {
                    "insight_id": str(memory.memory_id),
                    "statement": statement,
                    "type": "ANALOGY",
                    "epistemic_type": "HYPOTHESIZED",
                    "supporting_episode_ids": list(map(str, support)),
                    "counterexample_episode_ids": list(map(str, counter)),
                    "truth_confidence": confidence,
                    "novelty": novelty,
                    "utility": utility,
                    "differences": differences,
                    "causality_status": "NONE",
                    "status": "ACTIVE" if active else "CANDIDATE",
                    "critic_verdict": verdict,
                    "last_validated": utcnow().isoformat(),
                    "applicability_conditions": anchor.applicability_conditions,
                    "limitations": [
                        "Bounded to 300 recent authorized experiences and configured pair budget",
                        "Structural, temporal and distant-domain neighbors are search heuristics",
                    ],
                    "alternative_explanations": [
                        "Shared source events or domain confounding"
                    ],
                    "derivation": "STRUCTURAL_ANALOGY",
                }
                from memory.insights.lifecycle import seal

                payload = seal(payload, episode_evidence)
                connection.execute(
                    insert(r.insights).values(
                        id=memory.memory_id,
                        namespace_id=ctx.namespace_id,
                        feature_hash=key,
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
                proposals.append(payload)
            return proposals
