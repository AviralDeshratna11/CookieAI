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

SEVERITY = {"VALIDATED": 0, "WEAK": 1, "DISPUTED": 2, "REJECTED": 3}


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
        pending = self._candidates(ctx, max_pairs)
        if not pending:
            return []
        reviews = {}
        if self.memory.settings.reflection_backend == "compatible":
            # Read evidence, release the transaction, then call the model. Expensive
            # reasoning must not hold the namespace write lock.
            from models.serendipity import CompatibleSerendipity

            reviewer = CompatibleSerendipity(self.memory.settings)
            for item in pending[: self.memory.settings.reflection_max_model_candidates]:
                reviews[item["key"]] = reviewer.propose(
                    item["anchor"],
                    item["candidate"],
                    item["differences"],
                    item["support"],
                    item["counter"],
                    item["episode_evidence"],
                )
        return self._apply(ctx, pending, reviews)

    def _candidates(self, ctx, max_pairs):
        """Read-only pass: select an anchor, sample candidates, apply the
        structural/heuristic gates, and collect everything a model call or
        persistence pass would need. Nothing is written here."""
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
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
            pending = []
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
                confidence = min(
                    similarity, len(support) / (len(support) + len(counter) + 3)
                )
                novelty = (
                    0.6
                    if anchor.context_signature.get("domain")
                    != candidate.context_signature.get("domain")
                    else 0.2
                )
                differences = {
                    key2: [
                        anchor.context_signature.get(key2),
                        candidate.context_signature.get(key2),
                    ]
                    for key2 in anchor.context_signature
                    if anchor.context_signature.get(key2)
                    != candidate.context_signature.get(key2)
                }
                pending.append(
                    {
                        "key": key,
                        "anchor": anchor,
                        "anchor_memory": anchor_memory,
                        "candidate": candidate,
                        "candidate_memory": candidate_memory,
                        "ids": ids,
                        "support": support,
                        "counter": counter,
                        "episode_evidence": episode_evidence,
                        "evidence_revisions": {
                            (item.memory_id, item.revision) for item in episode_evidence
                        },
                        "verdict": verdict,
                        "confidence": confidence,
                        "novelty": novelty,
                        "shared": shared,
                        "differences": differences,
                    }
                )
            return pending

    def _apply(self, ctx, pending, reviews):
        with self.memory.engine.begin() as connection:
            repo = SQLMemoryRepository(connection, ctx)
            repo.lock_namespace()
            policy = self.memory.policy(repo)
            proposals = []
            for item in pending:
                if connection.execute(
                    select(r.insights.c.id).where(
                        r.insights.c.namespace_id == ctx.namespace_id,
                        r.insights.c.feature_hash == item["key"],
                    )
                ).first():
                    continue  # Recorded by a concurrent run since the read pass.
                verdict = item["verdict"]
                statement = (
                    f"Possible analogy: actions {sorted(item['shared'])} previously "
                    f"succeeded in structurally related contexts. Differences: "
                    f"{item['differences']}. Counterexamples: "
                    f"{len(item['counter'])}. This is not a universal or causal rule."
                )
                insight_type = "ANALOGY"
                applicability_conditions = item["anchor"].applicability_conditions
                alternative_explanations = ["Shared source events or domain confounding"]
                review = {}
                if item["key"] in reviews:
                    proposal, critique, metadata = reviews[item["key"]]
                    if item["evidence_revisions"] != {
                        (ev.memory_id, ev.revision) for ev in item["episode_evidence"]
                    }:
                        continue  # Evidence changed since the read pass; skip this run.
                    model_verdict = (
                        "REJECTED" if proposal.type == "NONE" else critique.verdict
                    )
                    verdict = max((verdict, model_verdict), key=SEVERITY.get)
                    if proposal.type != "NONE":
                        insight_type = proposal.type
                        if proposal.statement:
                            statement = proposal.statement
                        if proposal.applicability_conditions:
                            applicability_conditions = proposal.applicability_conditions
                        if proposal.alternative_explanations:
                            alternative_explanations = proposal.alternative_explanations
                    review = {
                        "proposal": proposal.model_dump(mode="json"),
                        "critique": critique.model_dump(),
                        **metadata,
                    }
                if verdict == "REJECTED":
                    continue
                utility = 0.6
                active = (
                    item["confidence"] >= policy.serendipity_confidence
                    and item["novelty"] >= policy.serendipity_novelty
                    and utility >= policy.serendipity_utility
                    and len(item["support"]) >= policy.minimum_support
                    and verdict == "VALIDATED"
                )
                evidence = [item["anchor_memory"], item["candidate_memory"]] + [
                    repo.get(episode_id) for episode_id in item["counter"]
                ]
                sources = item["ids"] + item["counter"]
                memory = self.memory._create(
                    repo,
                    MemoryCreate(
                        text=statement,
                        type="INSIGHT",
                        epistemic_type="HYPOTHESIZED",
                        source_type="DERIVED",
                        provenance_ids=sources,
                        truth_confidence=item["confidence"],
                        novelty=item["novelty"],
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
                    "type": insight_type,
                    "epistemic_type": "HYPOTHESIZED",
                    "supporting_episode_ids": list(map(str, item["support"])),
                    "counterexample_episode_ids": list(map(str, item["counter"])),
                    "truth_confidence": item["confidence"],
                    "novelty": item["novelty"],
                    "utility": utility,
                    "differences": item["differences"],
                    "causality_status": "NONE",
                    "status": "ACTIVE" if active else "CANDIDATE",
                    "critic_verdict": verdict,
                    "last_validated": utcnow().isoformat(),
                    "derivation": "STRUCTURAL_AND_LLM" if review else "STRUCTURAL_ANALOGY",
                    "model_review": review,
                    "applicability_conditions": applicability_conditions,
                    "limitations": [
                        "Bounded to 300 recent authorized experiences and configured pair budget",
                        "Structural, temporal and distant-domain neighbors are search heuristics",
                    ],
                    "alternative_explanations": alternative_explanations,
                }
                from memory.insights.lifecycle import seal

                payload = seal(payload, item["episode_evidence"])
                connection.execute(
                    insert(r.insights).values(
                        id=memory.memory_id,
                        namespace_id=ctx.namespace_id,
                        feature_hash=item["key"],
                        payload=payload,
                    )
                )
                for episode_id in item["support"]:
                    connection.execute(
                        insert(r.insight_evidence).values(
                            insight_id=memory.memory_id, episode_id=episode_id
                        )
                    )
                for episode_id in item["counter"]:
                    connection.execute(
                        insert(r.insight_counterexamples).values(
                            insight_id=memory.memory_id, episode_id=episode_id
                        )
                    )
                proposals.append(payload)
            return proposals
