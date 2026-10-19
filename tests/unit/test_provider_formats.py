from uuid import uuid4

import pytest
from pydantic import ValidationError

from memory.config import Settings
from memory.schemas import ExtractorContext, MessageInput, utcnow
from models.providers import CompatibleExtractor


@pytest.mark.parametrize("mode", ["json_schema", "prompt_json"])
def test_extractor_response_modes_preserve_validation(mode):
    extractor = CompatibleExtractor(
        Settings(_env_file=None, extraction_response_format=mode)
    )
    captured = {}

    def post(endpoint, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": '{"memories": []}'}}]}

    extractor.post = post
    context = ExtractorContext(
        agent_id=uuid4(),
        messages=[MessageInput(role="user", content="Hello")],
        conversation_date=utcnow(),
    )
    assert extractor.extract(context).memories == []
    if mode == "prompt_json":
        assert "response_format" not in captured
        assert '"$defs"' in captured["messages"][0]["content"]
    else:
        assert captured["response_format"]["type"] == "json_schema"
    extractor.post = lambda *_: {
        "choices": [{"message": {"content": '{"memories": [{"invented": true}]}'}}]
    }
    with pytest.raises(ValidationError):
        extractor.extract(context)
