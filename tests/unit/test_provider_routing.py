import httpx
import pytest

from memory.config import Settings
from models.providers import CompatibleEmbedding, Provider


@pytest.mark.parametrize("embedding_key", [None, "embedding-test-key"])
def test_separate_embedding_api_does_not_receive_llm_credentials(
    monkeypatch, embedding_key
):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host == "embed.example.invalid":
            return httpx.Response(200, json={"data": [{"embedding": [1.0] * 8}]})
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: client(transport=httpx.MockTransport(handle), **kw),
    )
    settings = Settings(
        _env_file=None,
        provider_base_url="https://llm.example.invalid/v1",
        provider_api_key="llm-test-key",
        embedding_provider_base_url="https://embed.example.invalid/v1",
        embedding_provider_api_key=embedding_key,
        embedding_dimensions=8,
    )
    CompatibleEmbedding(settings).embed_query("test")
    Provider(settings).post("/chat/completions", {})
    assert calls[0].url.path == "/v1/embeddings"
    assert calls[0].headers.get("Authorization") == (
        "Bearer " + embedding_key if embedding_key else None
    )
    assert calls[1].headers["Authorization"] == "Bearer llm-test-key"


def test_embedding_retains_shared_provider_when_no_override_is_set():
    settings = Settings(
        _env_file=None,
        provider_base_url="https://shared.example.invalid/v1",
        provider_api_key="shared-test-key",
    )
    embedder = CompatibleEmbedding(settings)
    assert embedder.base_url == settings.provider_base_url
    assert embedder.api_key.get_secret_value() == "shared-test-key"


def test_nvidia_query_passage_and_batch_order_are_distinct():
    settings = Settings(
        _env_file=None, embedding_dimensions=2048, embedding_input_type_mode="nvidia"
    )
    embedder = CompatibleEmbedding(settings)
    calls = []

    def post(endpoint, payload):
        calls.append(payload)
        inputs = payload["input"]
        count = len(inputs) if isinstance(inputs, list) else 1
        return {
            "data": [
                {"index": i, "embedding": [1.0 if j == i else 0.0 for j in range(2048)]}
                for i in reversed(range(count))
            ]
        }

    embedder.post = post
    embedder.embed("document")
    embedder.embed_query("query")
    vectors = embedder.embed_many(["first", "second"])
    assert [item["input_type"] for item in calls] == ["passage", "query", "passage"]
    assert all(item["truncate"] == "NONE" for item in calls)
    assert vectors[0][0] == vectors[1][1] == 1.0
    embedder.post = lambda *args: {
        "data": [{"index": 0, "embedding": [1.0] * 2048}] * 2
    }
    with pytest.raises(ValueError, match="input identities"):
        embedder.embed_many(["first", "second"])
