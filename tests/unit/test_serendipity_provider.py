import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from memory.config import Settings
from memory.experiences.service import Experience
from models.serendipity import CompatibleSerendipity


def _experience(experience_id):
    now = datetime.now(timezone.utc)
    return Experience(
        experience_id=experience_id,
        description="A test experience",
        context_signature={"domain": "test"},
        problem_pattern="overload",
        actions_attempted=["rate_limiter"],
        successful_actions=["applied a rate limiter"],
        failed_actions=[],
        outcome_pattern="success",
        applicability_conditions=[],
        exceptions=[],
        source_episode_ids=[uuid4()],
        confidence=0.5,
        success_count=1,
        failure_count=0,
        first_observed=now,
        last_observed=now,
    )


def test_generator_cannot_invent_experience_ids_outside_the_supplied_pair():
    anchor_id, candidate_id, other = uuid4(), uuid4(), uuid4()
    anchor, candidate = _experience(anchor_id), _experience(candidate_id)
    model = CompatibleSerendipity(
        Settings(_env_file=None, extraction_response_format="prompt_json")
    )
    calls = []

    def post(endpoint, payload):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "type": "ANALOGY",
                                "statement": "Unsupported association",
                                "supporting_experience_ids": [str(anchor_id), str(other)],
                                "counterexample_episode_ids": [],
                            }
                        )
                    }
                }
            ]
        }

    model.post = post
    with pytest.raises(ValueError, match="evidence identities"):
        model.propose(anchor, candidate, {}, [], [], [])
    assert len(calls) == 1  # Invalid generation never reaches the critic call.
