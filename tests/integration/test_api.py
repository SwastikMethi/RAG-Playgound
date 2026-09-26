import pytest
from fastapi.testclient import TestClient

from app.settings import Settings
from rag_runtime.contracts import validate
from tests.conftest import TEST_URL

pytestmark = pytest.mark.integration
TOKEN = "test-token-which-is-long-and-private"


@pytest.fixture
def client(tmp_path):
    from app.main import create_app
    settings = Settings(app_token=TOKEN, mode="test", database_url=TEST_URL, artifact_root=tmp_path)
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        yield c


def test_auth_contracts_and_immutable_configuration(client):
    for path in ["/projects", "/system/profiles", "/runs/missing/events", "/sources/missing/file"]:
        response = client.get("/api/v1"+path, headers={"Authorization":"Bearer wrong"})
        assert response.status_code == 401
        assert TOKEN not in response.text
    assert client.get("/api/v1/health", headers={"Authorization":""}).status_code == 200
    capabilities = client.get("/api/v1/system/capabilities").json()
    assert capabilities["mode"] == "test" and len(capabilities["items"]) == 6
    assert all(validate(c,"openapi.yaml","Capability") for c in capabilities["items"])
    project = client.post("/api/v1/projects", json={"name":"API test"}).json()
    assert validate(project,"openapi.yaml","Project")
    cfg = capabilities["items"][0]["default_config"]
    first = client.post(f"/api/v1/projects/{project['id']}/configurations",json={"name":"Lexical", "config":cfg}).json()
    second = client.post(f"/api/v1/projects/{project['id']}/configurations",json={"name":"Lexical edited", "config":cfg,
                         "based_on_config_id":first["id"]}).json()
    assert first["revision"] == 1 and second["revision"] == 2 and first["family_id"] == second["family_id"]
    assert client.get(f"/api/v1/configurations/{first['id']}").json()["name"] == "Lexical"
    assert validate(second,"openapi.yaml","Configuration")
