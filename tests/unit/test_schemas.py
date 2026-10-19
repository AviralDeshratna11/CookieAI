from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from memory.schemas import Candidate, MemoryCreate, MemoryPatch
from models.providers import HashEmbedding, validate_vector


@pytest.mark.parametrize(
    "changes",
    [
        {"text": "  "},
        {"truth_confidence": 1.1},
        {"truth_confidence": float("nan")},
        {"importance": -0.1},
        {"observed_at": datetime(2026, 1, 1)},
        {"epistemic_type": "VERIFIED_FACT"},
        {"owner_id": str(uuid4())},
        {"epistemic_type": "INFERRED"},
        {"source_type": "DERIVED"},
        {
            "valid_from": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "valid_until": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    ],
)
def test_invalid_memories(changes):
    with pytest.raises(ValidationError):
        MemoryCreate.model_validate(
            {"text": "Project Alpha uses PostgreSQL", **changes}
        )


def test_timezone_normalized():
    memory = MemoryCreate(
        text="Valid",
        observed_at=datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=5))),
    )
    assert memory.observed_at.hour == 7


def test_memory_worthiness_is_not_truth_confidence():
    candidate = Candidate(
        text="Alpha uses Postgres",
        source_span="Postgres",
        source_message_id=uuid4(),
        reason_for_storage="project decision",
        truth_confidence=0.1,
        importance=1,
        future_utility=1,
        persistence=1,
        specificity=1,
        novelty=1,
        personal_relevance=1,
        goal_relevance=1,
        salience=1,
        repetition=1,
    )
    assert candidate.memory_value() == pytest.approx(1)
    assert candidate.truth_confidence == 0.1


@pytest.mark.parametrize("vector", [[0] * 8, [float("inf")] * 8, [1] * 7])
def test_invalid_embeddings(vector):
    with pytest.raises(ValueError):
        validate_vector(vector, 8)


def test_test_embedding_deterministic_normalized():
    model = HashEmbedding()
    vector = model.embed("Postgres database choice")
    assert vector == model.embed("Postgres database choice")
    assert sum(x * x for x in vector) == pytest.approx(1)


def test_patch_forbids_nulls_and_requires_revision():
    with pytest.raises(ValidationError):
        MemoryPatch(text="changed")
    with pytest.raises(ValidationError):
        MemoryPatch(expected_revision=1, text=None)
