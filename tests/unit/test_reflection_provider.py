import json
from uuid import uuid4

import pytest

from memory.config import Settings
from models.reflection import CompatibleReflection


def test_generator_cannot_remove_counterevidence_or_invent_sources():
    source, counter = uuid4(), uuid4()
    model = CompatibleReflection(
        Settings(_env_file=None, extraction_response_format="prompt_json")
    )
    calls = []

    def post(endpoint, payload):
        calls.append(payload)
        assert "response_format" not in payload
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "statement": "Unsupported association",
                                "supporting_episode_ids": [str(source)],
                                "counterexample_episode_ids": [],
                            }
                        )
                    }
                }
            ]
        }

    model.post = post
    with pytest.raises(ValueError, match="evidence identities"):
        model.review("tool config", [source], [counter], [])
    assert len(calls) == 1  # Invalid generation never reaches the approval call.
