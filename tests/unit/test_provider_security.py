import pytest
from rag_runtime.providers import Gateway, Profile
from rag_runtime.errors import Problem


@pytest.mark.asyncio
async def test_provider_connection_pins_validated_dns_and_retains_tls_hostname(monkeypatch):
    import rag_runtime.providers as providers

    calls = []

    async def resolve(host, allowlist):
        calls.append((host, allowlist))
        return "203.0.113.7"

    monkeypatch.setattr(providers, "resolve_host", resolve, raising=False)
    profile = Profile(
        id="owner",
        label="Owner",
        model="answer",
        operations=["generation"],
        base_url="https://api.example.test/v1",
    )
    endpoint = await Gateway().endpoint(profile)
    assert str(endpoint["url"]) == "https://203.0.113.7/v1"
    assert endpoint["headers"]["Host"] == "api.example.test"
    assert endpoint["extensions"]["sni_hostname"] == "api.example.test"
    assert calls == [("api.example.test", ["api.example.test"])]

    async def reject(*args):
        raise Problem("HOST_NOT_ALLOWED", "Unsafe destination.")

    monkeypatch.setattr(providers, "resolve_host", reject)
    with pytest.raises(Problem):
        await Gateway().endpoint(profile)
