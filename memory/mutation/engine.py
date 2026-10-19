from enum import Enum
from uuid import UUID

from memory.schemas import Field, MemoryCreate, StrictModel


class MutationKind(str, Enum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    REINFORCEMENT = "REINFORCEMENT"
    REFINEMENT = "REFINEMENT"
    TEMPORAL_UPDATE = "TEMPORAL_UPDATE"
    CORRECTION = "CORRECTION"
    CONTRADICTION = "CONTRADICTION"
    SUPERSESSION = "SUPERSESSION"
    EXCEPTION = "EXCEPTION"
    IRRELEVANT = "IRRELEVANT"


class MutationRequest(StrictModel):
    candidate: MemoryCreate
    operation: MutationKind
    target_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)


def classify(candidate, previous):
    if candidate.text.strip() == previous.text.strip():
        return MutationKind.DUPLICATE
    if not all(
        (
            candidate.subject,
            candidate.predicate,
            candidate.object,
            previous.subject,
            previous.predicate,
            previous.object,
        )
    ):
        return MutationKind.NEW
    if (candidate.subject.casefold(), candidate.predicate.casefold()) != (
        previous.subject.casefold(),
        previous.predicate.casefold(),
    ):
        return MutationKind.NEW
    if candidate.epistemic_type != previous.epistemic_type:
        return MutationKind.NEW
    if candidate.object.casefold() == previous.object.casefold():
        return MutationKind.REFINEMENT
    if candidate.valid_from and candidate.valid_from > (
        previous.valid_from or previous.observed_at
    ):
        return MutationKind.TEMPORAL_UPDATE
    if (
        candidate.valid_until
        and previous.valid_from
        and candidate.valid_until <= previous.valid_from
    ):
        return MutationKind.EXCEPTION
    return MutationKind.CONTRADICTION
