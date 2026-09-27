import pytest
from tests.integration.test_api import client as client

pytestmark = pytest.mark.integration


def test_readiness_and_operational_log_redaction(client, monkeypatch, capsys):
    from alembic.script import ScriptDirectory

    response = client.get("/api/v1/system/readiness")
    assert response.json()["status"] == "ok"
    assert response.headers["x-request-id"]
    client.get("/api/v1/projects?q=private-search-text")
    log = capsys.readouterr().out
    assert '"event":"http"' in log and "private-search-text" not in log
    assert client.app.state.settings.app_token.get_secret_value() not in log
    monkeypatch.setattr(ScriptDirectory, "get_heads", lambda self: ["future-migration"])
    assert client.get("/api/v1/system/readiness").json()["status"] == "degraded"


def test_actual_body_cap_csp_and_saved_fixture_mode(client):
    # No trustworthy content-length: bound the bytes received before JSON parsing.
    response = client.post(
        "/api/v1/projects",
        content=(b"x" * 65536 for _ in range(5)),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413, response.text
    assert "REQUEST_TOO_LARGE" in response.text
    health = client.get("/api/v1/health")
    assert "object-src 'none'" in health.headers["content-security-policy"]
    from tests.integration.test_export import completed_lane

    worker, run, _ = completed_lane(client, "bm25")
    assert run["mode"] == "test"
    client.app.state.settings.mode = "live"
    saved = client.get("/api/v1/runs/" + run["id"]).json()
    assert saved["mode"] == "test"
    worker.close()
