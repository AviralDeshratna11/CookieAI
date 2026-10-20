"""Bounded contrastive hypotheses from explicit real-labeled episode outcomes.

Different observed rates propose a candidate, never a causal claim or an active
procedure. Session/event deduplication is an operational proxy for independence.
"""

import hashlib
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import delete, insert, select, update

from database import learning_tables as learning
from database import reflection_tables as r
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.episodes.service import Episode
from memory.insights.lifecycle import seal
from memory.provenance.policy import evidence_policy
from memory.reflection.engine import SENSITIVE_TERMS
from memory.schemas import MemoryCreate, Status, utcnow
from memory.security.auth import require_scope


def proposals(observations):
    groups = defaultdict(lambda: defaultdict(list))
    for memory, episode in observations:
        if episode.evidence_origin != "REAL" or episode.outcome.casefold() not in {
            "success",
            "failure",
        }:
            continue
        context = {
            key: value.strip().casefold()[:200]
            for key, value in episode.context.items()
        }
        if not context.get("goal_type") or not context.get("domain"):
            continue
        if any(term in str(context).replace(" ", "_") for term in SENSITIVE_TERMS):
            continue
        tools = tuple(sorted({attempt.tool for attempt in episode.attempts}))
        for dimension in ("environment", "workflow_stage"):
            value = context.get(dimension)
            if not value:
                continue
            controls = tuple(
                (key, context.get(key, ""))
                for key in (
                    "goal_type",
                    "domain",
                    "error_category",
                    "environment",
                    "workflow_stage",
                )
                if key != dimension
            )
            groups[(dimension, controls, tools)][value].append((memory, episode))
    result = {}
    for key, variants in sorted(groups.items(), key=lambda item: str(item[0])):
        values = sorted(variants)[:10]
        for index, left in enumerate(values):
            for right in values[index + 1 :]:
                selected, sessions, producers = {}, set(), set()
                for value in (left, right):
                    selected[value] = []
                    for memory, episode in variants[value]:
                        # Canonical provenance supports at most 100 parents. Keep
                        # both cohorts and their reported denominators bounded.
                        if len(selected[value]) >= 50:
                            break
                        producer = episode.event_id or episode.episode_id
                        if (
                            producer in producers
                            or memory.source_session_id in sessions
                        ):
                            continue
                        sessions.add(memory.source_session_id)
                        producers.add(producer)
                        selected[value].append((memory, episode))
                if any(len(selected[value]) < 3 for value in (left, right)):
                    continue
                counts = {
                    value: {
                        "success": sum(
                            episode.outcome.casefold() == "success"
                            for _, episode in selected[value]
                        ),
                        "total": len(selected[value]),
                    }
                    for value in (left, right)
                }
                rates = [
                    counts[value]["success"] / counts[value]["total"]
                    for value in (left, right)
                ]
                if abs(rates[0] - rates[1]) < 0.5:
                    continue
                definition = (key, left, right)
                digest = hashlib.sha256(repr(definition).encode()).hexdigest()
                evidence = [
                    memory for value in (left, right) for memory, _ in selected[value]
                ]
                result[digest] = {
                    "dimension": key[0],
                    "controls": list(key[1]),
                    "tools": list(key[2]),
                    "values": [left, right],
                    "observed_counts": counts,
                    "evidence": evidence,
                    "statement": f"Observed outcome contrast under {key[0]}={left} versus {right} for goal {dict(key[1])['goal_type']} in {dict(key[1])['domain']}. This is a conditional association requiring review.",
                }
                if len(result) >= 100:
                    return result
    return result


class ContrastiveDiscovery:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def run(self, ctx):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            rows = (
                db.execute(
                    select(learning.episodes.c.payload)
                    .join(t.memories, t.memories.c.id == learning.episodes.c.id)
                    .where(t.memories.c.namespace_id == ctx.namespace_id)
                    .order_by(t.memories.c.created_at.desc(), t.memories.c.id)
                    .limit(200)
                )
                .scalars()
                .all()
            )
            episodes = [Episode.model_validate(payload) for payload in rows]
            visible = repo.get_many(
                [episode.episode_id for episode in episodes], strict=False
            )
            candidates = proposals(
                [
                    (visible[episode.episode_id], episode)
                    for episode in episodes
                    if episode.episode_id in visible
                    and visible[episode.episode_id].status.value == "ACTIVE"
                    and repo.valid_at(visible[episode.episode_id])
                ]
            )
            previous = {
                row["feature_hash"]: dict(row)
                for row in db.execute(
                    select(r.insights).where(
                        r.insights.c.namespace_id == ctx.namespace_id,
                        r.insights.c.payload["derivation"].as_string()
                        == "CONTRASTIVE_OUTCOMES",
                    )
                ).mappings()
            }
            changed = []
            keys = sorted(
                set(candidates) | set(previous),
                key=lambda key: (
                    previous.get(key, {}).get("payload", {}).get("last_validated", ""),
                    key,
                ),
            )
            for key in keys:
                if len(changed) >= 8:
                    break
                candidate, prior = candidates.get(key), previous.get(key)
                old = (
                    repo.get_many([prior["id"]], strict=False).get(prior["id"])
                    if prior
                    else None
                )
                if prior and old is None:
                    continue
                if not candidate:
                    if prior["payload"]["status"] == "INVALIDATED":
                        continue
                    payload = seal(
                        {
                            **prior["payload"],
                            "status": "INVALIDATED",
                            "truth_confidence": 0,
                            "limitations": [
                                "Contrast no longer supported within the bounded current evidence window"
                            ],
                        },
                        [],
                        prior["payload"],
                    )
                    repo.save(
                        old.model_copy(
                            update={
                                "status": Status.DISPUTED,
                                "revision": old.revision + 1,
                                "updated_at": utcnow(),
                            }
                        ),
                        self.memory.vector(old.text),
                        "UPDATED",
                    )
                    db.execute(
                        update(r.insights)
                        .where(r.insights.c.id == old.memory_id)
                        .values(payload=payload)
                    )
                    self.memory._invalidate_descendants(repo, old.memory_id)
                    changed.append(payload)
                    continue
                evidence = candidate.pop("evidence")
                revisions = {str(item.memory_id): item.revision for item in evidence}
                if (
                    prior
                    and prior["payload"].get("evidence_revisions") == revisions
                    and prior["payload"]["status"]
                    in {"CANDIDATE", "REJECTED", "ACTIVE", "DORMANT", "SUPERSEDED"}
                ):
                    continue
                policy = evidence_policy(evidence + ([old] if old else []))
                ids = sorted({item.memory_id for item in evidence}, key=str)
                if old:
                    canonical = old.model_copy(
                        update={
                            "status": Status.DISPUTED,
                            "revision": old.revision + 1,
                            "updated_at": utcnow(),
                            "provenance_ids": ids,
                            **policy,
                        }
                    )
                    repo.save(canonical, self.memory.vector(canonical.text), "UPDATED")
                    db.execute(
                        delete(t.provenance).where(
                            t.provenance.c.child_id == old.memory_id,
                            t.provenance.c.kind == "DERIVED_FROM",
                        )
                    )
                    for identity in ids:
                        db.execute(
                            insert(t.provenance).values(
                                parent_id=identity,
                                child_id=old.memory_id,
                                namespace_id=ctx.namespace_id,
                                kind="DERIVED_FROM",
                            )
                        )
                    self.memory._invalidate_descendants(repo, old.memory_id)
                else:
                    canonical = self.memory._create(
                        repo,
                        MemoryCreate(
                            text=candidate["statement"],
                            type="INSIGHT",
                            epistemic_type="CORRELATED",
                            source_type="DERIVED",
                            provenance_ids=ids,
                            truth_confidence=0.5,
                            expires_at=utcnow()
                            + timedelta(
                                days=self.memory.settings.candidate_retention_days
                            ),
                            **policy,
                        ),
                    )
                    canonical = canonical.model_copy(
                        update={
                            "status": Status.DISPUTED,
                            "revision": canonical.revision + 1,
                        }
                    )
                    repo.save(canonical, self.memory.vector(canonical.text), "DISPUTED")
                payload = seal(
                    {
                        "insight_id": str(canonical.memory_id),
                        "type": "CONTRASTIVE_OUTCOME",
                        "status": "CANDIDATE",
                        "truth_confidence": 0.5,
                        "derivation": "CONTRASTIVE_OUTCOMES",
                        **candidate,
                        "supporting_memory_ids": list(map(str, ids)),
                        "support_count": len(ids),
                        "counterexample_search": "All selected outcomes, including success and failure, count in each observed exposure denominator",
                        "limitations": [
                            "Observational, not causal",
                            "Session/event identity is not proof of statistical independence",
                            "At most 200 recent authorized episodes; not a population estimate",
                        ],
                        "alternative_explanations": [
                            "Unmeasured environment/task differences",
                            "Selection and reporting bias",
                        ],
                        "falsification": "New comparable outcomes reduce or reverse the observed contrast",
                        "confidence_basis": "Unvalidated candidate; fixed heuristic confidence, not a probability",
                    },
                    evidence,
                    prior["payload"] if prior else None,
                )
                if prior:
                    db.execute(
                        update(r.insights)
                        .where(r.insights.c.id == canonical.memory_id)
                        .values(payload=payload)
                    )
                else:
                    db.execute(
                        insert(r.insights).values(
                            id=canonical.memory_id,
                            namespace_id=ctx.namespace_id,
                            feature_hash=key,
                            payload=payload,
                        )
                    )
                changed.append(payload)
            return changed
