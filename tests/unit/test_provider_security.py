import pytest
import asyncio
import socket
from rag_runtime.providers import Gateway, Profile
from rag_runtime.errors import Problem


@pytest.mark.asyncio
async def test_provider_connection_pins_validated_dns_and_retains_tls_hostname(monkeypatch):
    calls = []
    address = "203.0.113.7"

    async def lookup(host, port, *, type):
        calls.append((host, port))
        return [(socket.AF_INET, type, 6, "", (address, port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
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
    assert calls == [("api.example.test", 443)]
    profile.base_url = "http://api.example.test:8123/v1"
    endpoint = await Gateway().endpoint(profile)
    assert endpoint["headers"]["Host"] == "api.example.test:8123"
    assert calls[-1] == ("api.example.test", 8123)
    address = "169.254.169.254"
    with pytest.raises(Problem):
        await Gateway().endpoint(profile)
