"""Bounded, falsifiable miners over attributed structured observations.

No natural-language event extraction or causal inference occurs here. Evidence
without explicit fields remains eligible for the separate model-assisted miner.
"""

import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from itertools import combinations
from uuid import uuid4

from sqlalchemy import delete, insert, select, update

from database import reflection_tables as r
from database import tables as t
from database.repositories.memory import SQLMemoryRepository
from memory.insights.lifecycle import seal
from memory.provenance.policy import evidence_policy
from memory.reflection.engine import SENSITIVE_TERMS
from memory.schemas import Memory, MemoryCreate, Status, utcnow
from memory.security.auth import NotFound, require_scope


def normalize(value):
    return " ".join((value or "").casefold().split())


def key_for(feature):
    return hashlib.sha256(json.dumps(feature, sort_keys=True).encode()).hexdigest()


def independent(items):
    """A session and an explicit producer source may each contribute at most once."""
    sessions, producers, result = set(), set(), []
    for item in sorted(items, key=lambda m: str(m.memory_id)):
        producer = item.source_id or item.memory_id
        if item.source_session_id in sessions or producer in producers:
            continue
        sessions.add(item.source_session_id)
        producers.add(producer)
        result.append(item)
    return result


def features(memories):
    groups = defaultdict(list)
    slots = defaultdict(list)
    sessions = defaultdict(list)
    for item in memories:
        subject, predicate, value = map(
            normalize, (item.subject, item.predicate, item.object)
        )
        if subject and predicate and value:
            feature = ("STRUCTURED_RECURRENCE", subject, predicate, value)
            groups[feature].append(item)
            slots[(subject, predicate)].append(item)
            if predicate == "depends_on":
                groups[("DECLARED_DEPENDENCY", subject, value)].append(item)
        # Co-mention is deliberately weaker than an inferred relationship.
        for left, right in combinations(
            sorted(set(map(normalize, item.entities)))[:8], 2
        ):
            groups[("ENTITY_CO_MENTION", left, right)].append(item)
        if predicate == "event" and value:
            sessions[item.source_session_id].append(item)
            if item.event_at:
                groups[("UTC_TIME_WINDOW", value, str(item.event_at.hour // 6))].append(
                    item
                )
    for items in sessions.values():
        ordered = sorted(items, key=lambda m: m.event_at or m.observed_at)
        for left, right in zip(ordered, ordered[1:]):
            delta = (right.event_at or right.observed_at) - (
                left.event_at or left.observed_at
            )
            if 0 < delta.total_seconds() <= 3600:
                feature = (
                    "OBSERVED_SEQUENCE",
                    normalize(left.object),
                    normalize(right.object),
                )
                groups[feature].extend([left, right])
    return groups, slots


class StructuredDiscovery:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("write")
    def run(self, ctx, maximum=8):
        with self.memory.engine.begin() as db:
            repo = SQLMemoryRepository(db, ctx)
            repo.lock_namespace()
            direct = [
                m
                for m in repo.recent(limit=300)
                if m.status.value in {"ACTIVE", "DISPUTED"}
                and m.source_type not in {"DERIVED", "TOOL"}
                and not m.provenance_ids
                and not (m.expires_at and m.expires_at <= utcnow())
                and not (m.valid_until and m.valid_until <= utcnow())
                and not (m.valid_from and m.valid_from > utcnow())
            ]
            digest = key_for(sorted((str(m.memory_id), m.revision) for m in direct))
            groups, slots = features(direct)
            existing = {
                row["feature_hash"]: row
                for row in db.execute(
                    select(r.insights).where(
                        r.insights.c.namespace_id == ctx.namespace_id
                    )
                ).mappings()
                if row["payload"].get("derivation") == "STRUCTURED_RULES"
            }
            # Include disappeared features so corrections retire their old conclusions.
            for row in existing.values():
                groups.setdefault(tuple(row["payload"]["feature_definition"]), [])
            pending = sorted(
                groups,
                key=lambda f: (
                    existing.get(key_for(f), {})
                    .get("payload", {})
                    .get("last_validated", ""),
                    f,
                ),
            )
            results = []
            for feature in pending:
                key = key_for(feature)
                prior = existing.get(key, {}).get("payload", {})
                if prior.get("input_digest") == digest:
                    continue
                raw = [m for m in groups[feature] if m.status.value == "ACTIVE"]
                support = independent(raw)
                if len(support) < 3 and not prior:
                    continue
                counter = []
                if feature[0] == "STRUCTURED_RECURRENCE":
                    counter = independent(
                        [
                            m
                            for m in slots[feature[1:3]]
                            if normalize(m.object) != feature[3]
                        ]
                    )
                elif feature[0] == "UTC_TIME_WINDOW":
                    counter = independent(
                        [
                            m
                            for m in direct
                            if normalize(m.predicate) == "event"
                            and normalize(m.object) == feature[1]
                            and m.event_at
                            and str(m.event_at.hour // 6) != feature[2]
                        ]
                    )
                # Sequence support needs both ordered events per session in provenance.
                evidence = list({m.memory_id: m for m in raw + counter}.values())
                statement = (
                    "Recorded association "
                    + json.dumps(feature, ensure_ascii=False)
                    + ". Limited to attributed observations; not a causal or universal rule."
                )
                if any(term in statement.replace(" ", "_") for term in SENSITIVE_TERMS):
                    continue
                confidence = len(support) / (len(support) + len(counter) + 3)
                status = (
                    "INVALIDATED"
                    if len(support) < 3
                    else "DISPUTED"
                    if len(counter) >= len(support)
                    else "ACTIVE"
                    if confidence >= 0.65
                    and feature[0] in {"STRUCTURED_RECURRENCE", "DECLARED_DEPENDENCY"}
                    else "CANDIDATE"
                )
                old = None
                if prior:
                    try:
                        old = repo.get(existing[key]["id"])
                    except NotFound:
                        continue
                if not evidence and old:
                    # Retain existing lineage; all sources may be superseded rather than deleted.
                    evidence = [repo.get(identity) for identity in old.provenance_ids]
                policy = evidence_policy(evidence + ([old] if old else []))
                ids = [m.memory_id for m in evidence]
                expiry = (
                    None
                    if status == "ACTIVE"
                    else utcnow()
                    + timedelta(days=self.memory.settings.candidate_retention_days)
                )
                if old:
                    values = old.model_dump()
                    values.update(
                        provenance_ids=ids,
                        truth_confidence=confidence,
                        status="ACTIVE" if status == "ACTIVE" else "DISPUTED",
                        revision=old.revision + 1,
                        updated_at=utcnow(),
                        expires_at=expiry,
                        **policy,
                    )
                    canonical = Memory.model_validate(values)
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
                            text=statement,
                            type="INSIGHT",
                            epistemic_type="CORRELATED",
                            source_type="DERIVED",
                            provenance_ids=ids,
                            truth_confidence=confidence,
                            expires_at=expiry,
                            **policy,
                        ),
                    )
                    if status != "ACTIVE":
                        canonical = canonical.model_copy(
                            update={
                                "status": Status.DISPUTED,
                                "revision": canonical.revision + 1,
                            }
                        )
                        canonical = Memory.model_validate(canonical.model_dump())
                        repo.save(canonical, self.memory.vector(statement), "DISPUTED")
                payload = seal(
                    {
                        "insight_id": str(canonical.memory_id),
                        "statement": statement,
                        "type": feature[0],
                        "status": status,
                        "truth_confidence": confidence,
                        "support_count": len(support),
                        "counterexample_count": len(counter),
                        "supporting_memory_ids": [str(m.memory_id) for m in raw],
                        "counterexample_memory_ids": [
                            str(m.memory_id) for m in counter
                        ],
                        "feature_definition": list(feature),
                        "input_digest": digest,
                        "derivation": "STRUCTURED_RULES",
                        "applicability_conditions": [
                            "Exact normalized feature match in supplied structured fields"
                        ],
                        "limitations": [
                            "At most 300 recent authorized sources; distinct sessions/producers are a proxy for independence.",
                            "Co-mentions, UTC windows and sequences remain candidates; no causality or missing-event inference.",
                        ],
                        "alternative_explanations": [
                            "Selection bias, duplicated real-world events, or confounding."
                        ],
                        "critic_verdict": "VALIDATED" if status == "ACTIVE" else "WEAK",
                        "search_coverage": {"sources": len(direct), "maximum": 300},
                    },
                    evidence,
                    prior,
                )
                if old:
                    db.execute(
                        update(r.insights)
                        .where(r.insights.c.id == old.memory_id)
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
                results.append(payload)
                if len(results) >= maximum:
                    break
            db.execute(
                insert(r.jobs).values(
                    id=uuid4(),
                    namespace_id=ctx.namespace_id,
                    cursor_time=utcnow(),
                    payload={
                        "stage": "structured",
                        "source_count": len(direct),
                        "feature_count": len(groups),
                        "evaluated": len(results),
                        "input_digest": digest,
                    },
                )
            )
            return results
