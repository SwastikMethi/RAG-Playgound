import httpx
import pytest

from rag_runtime.errors import Problem
from rag_runtime.providers import Profile


@pytest.mark.asyncio
async def test_provider_retries_before_text_but_never_after_partial_answer(monkeypatch):
    from rag_runtime.providers import Gateway

    monkeypatch.setenv("TEST_MODEL_KEY", "secret-never-in-events")
    profile = Profile(
        id="test",
        label="Test",
        model="model",
        operations=["generation"],
        base_url="https://provider.invalid/v1",
        api_key_env="TEST_MODEL_KEY",
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    attempts = []

    def handle(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"message": "private provider detail"}})
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"Hello 🪐"}}]}\n\ndata: [DONE]\n\n'
        )

    gateway = Gateway(transport=httpx.MockTransport(handle))
    config = dict(model="model", temperature=0, max_output_tokens=64, seed=None)
    chunks = [c async for c in gateway.stream(profile, config, [{"role": "user", "content": "hello"}])]
    assert len(attempts) == 2 and "".join(c.get("text", "") for c in chunks) == "Hello 🪐"
    assert "secret-never-in-events" not in str(chunks)
    attempts.clear()

    def broken(request):
        attempts.append(request)
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"Partial"}}]}\n\ndata: broken-json\n\n'
        )

    gateway = Gateway(transport=httpx.MockTransport(broken))
    with pytest.raises(Problem):
        async for _ in gateway.stream(profile, config, [{"role": "user", "content": "hello"}]):
            pass
    assert len(attempts) == 1
