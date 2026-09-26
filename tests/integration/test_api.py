import pytest
from fastapi.testclient import TestClient

from app.settings import Settings
from rag_runtime.contracts import validate
from tests.conftest import TEST_URL
import asyncio
import json
from uuid import uuid4

pytestmark = pytest.mark.integration
TOKEN = "test-token-which-is-long-and-private"


@pytest.fixture
def client(tmp_path):
    from app.main import create_app

    settings = Settings(
        app_token=TOKEN,
        mode="test",
        database_url=TEST_URL,
        artifact_root=tmp_path,
        qdrant_collection_prefix="rag_test",
    )
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        yield c


def test_auth_contracts_and_immutable_configuration(client):
    for path in ["/projects", "/system/profiles", "/runs/missing/events", "/sources/missing/file"]:
        response = client.get("/api/v1" + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401
        assert TOKEN not in response.text
    assert client.get("/api/v1/health", headers={"Authorization": ""}).status_code == 200
    capabilities = client.get("/api/v1/system/capabilities").json()
    assert capabilities["mode"] == "test" and len(capabilities["items"]) == 6
    assert all(validate(c, "openapi.yaml", "Capability") for c in capabilities["items"])
    project = client.post("/api/v1/projects", json={"name": "API test"}).json()
    assert validate(project, "openapi.yaml", "Project")
    cfg = capabilities["items"][0]["default_config"]
    first = client.post(
        f"/api/v1/projects/{project['id']}/configurations", json={"name": "Lexical", "config": cfg}
    ).json()
    second = client.post(
        f"/api/v1/projects/{project['id']}/configurations",
        json={"name": "Lexical edited", "config": cfg, "based_on_config_id": first["id"]},
    ).json()
    assert first["revision"] == 1 and second["revision"] == 2 and first["family_id"] == second["family_id"]
    assert client.get(f"/api/v1/configurations/{first['id']}").json()["name"] == "Lexical"
    assert validate(second, "openapi.yaml", "Configuration")


def test_bm25_upload_prepare_ask_replay_and_no_evidence(client):
    from workers.main import Worker

    worker = Worker(client.app.state.settings)
    project = client.post("/api/v1/projects", json={"name": "End to end"}).json()["id"]
    response = client.post(
        f"/api/v1/projects/{project}/sources/upload",
        files={
            "file": (
                "manual.md",
                "# Clock\nNEBULA-42 means clock drift. Synchronize the clock. 🪐",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 202, response.text
    source = response.json()
    asyncio.run(worker.run_once(source["job_id"]))
    source = client.get("/api/v1/sources/" + source["id"]).json()
    assert source["status"] == "ready", source
    corpus = client.post(
        f"/api/v1/projects/{project}/corpus-versions", json={"source_ids": [source["id"]]}
    ).json()
    cfg = client.get("/api/v1/system/capabilities").json()["items"][0]["default_config"]
    configuration = client.post(
        f"/api/v1/projects/{project}/configurations", json={"name": "BM25", "config": cfg}
    ).json()
    response = client.post(
        f"/api/v1/projects/{project}/preparations",
        headers={"Idempotency-Key": str(uuid4())},
        json={"corpus_version_id": corpus["id"], "config_id": configuration["id"]},
    )
    assert response.status_code == 202, response.text
    bundle = response.json()
    asyncio.run(worker.run_once(bundle["job_id"]))
    bundle = client.get("/api/v1/index-bundles/" + bundle["id"]).json()
    assert bundle["status"] == "ready", bundle
    for question, kind in [("What is NEBULA-42?", "answer"), ("zyxwvu", "insufficient_evidence")]:
        body = {
            "corpus_version_id": corpus["id"],
            "question": question,
            "lanes": [{"config_id": configuration["id"], "bundle_id": bundle["id"]}],
        }
        key = str(uuid4())
        response = client.post(
            f"/api/v1/projects/{project}/runs", json=body, headers={"Idempotency-Key": key}
        )
        assert response.status_code == 202, response.text
        run = response.json()
        assert (
            client.post(
                f"/api/v1/projects/{project}/runs", json=body, headers={"Idempotency-Key": key}
            ).json()["id"]
            == run["id"]
        )
        asyncio.run(worker.run_resource(run["id"]))
        result = client.get("/api/v1/runs/" + run["id"]).json()
        assert result["status"] == "completed", result
        lane = result["lanes"][0]
        assert lane["answer_kind"] == kind and lane["answer"]
        events = client.get("/api/v1/runs/" + run["id"] + "/events").text
        frames = [json.loads(line[6:]) for line in events.splitlines() if line.startswith("data: ")]
        assert [f["seq"] for f in frames] == list(range(1, len(frames) + 1))
        assert all(validate(f, "trace-event.schema.json") for f in frames)
        assert "".join(f["payload"]["text"] for f in frames if f["type"] == "answer.delta") == lane["answer"]
        response = client.get(f"/api/v1/runs/{run['id']}/lanes/{lane['id']}/evidence").json()
        validate(response, "openapi.yaml", "EvidenceList")
        evidence = response["evidence"]
        if kind == "answer":
            assert "[E1]" in lane["answer"] and evidence[0]["source_id"] == source["id"]
            assert lane["metrics"]["ttft_ms"] is not None
        else:
            assert not evidence and lane["metrics"]["ttft_ms"] is None
            assert any(f["type"] == "stage.skipped" and f["payload"]["stage"] == "generation" for f in frames)
    worker.close()
