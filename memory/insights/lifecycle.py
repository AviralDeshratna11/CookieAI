"""Shared typed finding metadata and revision history in the canonical insight store."""

import hashlib
from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from memory.retrieval.hybrid import terms
from memory.schemas import utcnow


class Finding(BaseModel):
    model_config = ConfigDict(extra="allow")
    insight_id: UUID
    statement: str = Field(min_length=1)
    type: str
    status: Literal[
        "CANDIDATE",
        "ACTIVE",
        "DISPUTED",
        "REJECTED",
        "DORMANT",
        "INVALIDATED",
        "SUPERSEDED",
        "EXPIRED",
    ]
    truth_confidence: float = Field(ge=0, le=1)
    causal: Literal[False] = False
    causality_status: Literal["NONE"] = "NONE"
    evidence_revisions: dict[str, int] = Field(default_factory=dict)
    state_revision: int = Field(default=1, ge=1)


def structural_key(kind, statement, conditions=()):
    # Retain negations and all lexical terms; do not merge on vector similarity.
    normalized = (
        kind,
        sorted(terms(statement)),
        sorted(" ".join(c.casefold().split()) for c in conditions),
    )
    return hashlib.sha256(repr(normalized).encode()).hexdigest()


def seal(payload, evidence, previous=None):
    previous = previous or {}
    timestamp = utcnow().isoformat()
    events = list(previous.get("state_history", []))
    if previous:
        events.append(
            {
                "status": previous["status"],
                "confidence": previous["truth_confidence"],
                "at": previous.get("last_validated"),
                "support_count": previous.get("support_count", 0),
                "counterexample_count": previous.get("counterexample_count", 0),
            }
        )
    return Finding.model_validate(
        {
            **payload,
            "evidence_revisions": {str(m.memory_id): m.revision for m in evidence},
            "state_revision": previous.get("state_revision", 0) + 1,
            "first_detected": previous.get("first_detected", timestamp),
            "last_validated": timestamp,
            "next_review_at": (utcnow() + timedelta(days=1)).isoformat(),
            "state_history": events[-30:],
            "derivation_version": "finding-lifecycle:v1",
            "confidence_basis": payload.get(
                "confidence_basis",
                "independent support / (support + counterexamples + 3); heuristic, not a calibrated probability",
            ),
        }
    ).model_dump(mode="json")
