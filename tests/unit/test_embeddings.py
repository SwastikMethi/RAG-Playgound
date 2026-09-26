import httpx
import pytest
from rag_runtime.providers import Gateway, Profile
from rag_runtime.errors import Problem


@pytest.mark.asyncio
async def test_embedding_dimensions_and_token_limits_are_not_silently_truncated(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    p = Profile(
        id="embedding",
        label="Embedding",
        model="model",
        operations=["embedding"],
        base_url="https://example.invalid/v1",
        api_key_env="TEST_KEY",
        dimensions=2,
        tokenizer="cl100k_base",
        max_input_tokens=256,
    )
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0, 0]}]})

    gateway = Gateway(transport=httpx.MockTransport(respond))
    with pytest.raises(Problem, match="dimension"):
        await gateway.embed(p, ["short text"])
    requests.clear()
    with pytest.raises(Problem, match="token limit"):
        await gateway.embed(p, ["word " * 1000])
    assert not requests
