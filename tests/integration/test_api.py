import pytest
from fastapi.testclient import TestClient

from app.settings import Settings
from rag_runtime.contracts import validate, validator, schema_file
from tests.conftest import TEST_URL
import asyncio
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path):
    from app.main import create_app

    settings = Settings(
        mode="test",
        database_url=TEST_URL,
        artifact_root=tmp_path,
        qdrant_collection_prefix="rag_test",
        _env_file=None,
    )
    with TestClient(create_app(settings)) as c:
        send = c.request

        def checked(method, url, *args, **kwargs):
            response = send(method, url, *args, **kwargs)
            path = urlsplit(str(url)).path.removeprefix("/api/v1")
            for template, operations in schema_file("openapi.yaml")["paths"].items():
                if not re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), path):
                    continue
                operation = operations.get(method.lower())
                if not operation:
                    break
                status = str(response.status_code)
                assert status in operation["responses"], f"{method} {path}: undeclared status {status}"
                if "application/json" in response.headers.get("content-type", ""):
                    escaped = template.replace("~", "~0").replace("/", "~1")
                    validator(
                        "openapi.yaml",
                        pointer=f"/paths/{escaped}/{method.lower()}/responses/{status}/content/application~1json/schema",
                    ).validate(response.json())
                break
            return response

        c.request = checked
        yield c


def test_token_free_contracts_and_immutable_configuration(client):
    client.headers.pop("Authorization", None)
    for path, status in [
        ("/health", 200),
        ("/projects", 200),
        ("/system/profiles", 200),
        ("/runs/missing/events", 404),
        ("/sources/missing/file", 404),
        ("/exports/missing/download", 404),
    ]:
        assert client.get("/api/v1" + path).status_code == status
        if path != "/health":
            assert client.get("/api/v1" + path, headers={"Origin": "https://other.example"}).status_code == 403
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


def test_collection_pagination_contracts_and_scopes(client):
    from app.models import Source, Corpus, CorpusSource, Configuration
    from rag_runtime.contracts import digest
    from rag_runtime.registry import defaults

    project = client.post("/api/v1/projects", json={"name": "Pagination"}).json()["id"]
    config = defaults("bm25", client.app.state.profiles)
    with client.app.state.store.session() as s:
        for i in range(3):
            source = Source(project_id=project, display_name=f"source-{i}", kind="file", source_metadata={})
            corpus = Corpus(project_id=project, ordinal=i + 1, content_fingerprint=digest(str(i)))
            s.add_all([source, corpus])
            s.flush()
            s.add(CorpusSource(corpus_version_id=corpus.id, source_id=source.id, ordinal=0))
            s.add(
                Configuration(
                    project_id=project, name=f"config-{i}", config=config, config_sha256=digest(config)
                )
            )
    for suffix in ["sources", "corpus-versions", "configurations"]:
        path = f"/api/v1/projects/{project}/{suffix}"
        first = client.get(path, params={"limit": 2}).json()
        assert len(first["items"]) == 2 and first["next_cursor"]
        last = client.get(path, params={"limit": 2, "cursor": first["next_cursor"]}).json()
        assert len(last["items"]) == 1 and last["next_cursor"] is None
        assert not {r["id"] for r in first["items"]} & {r["id"] for r in last["items"]}
        assert all(r["project_id"] == project for r in first["items"] + last["items"])
        assert client.get(path, params={"cursor": "invalid"}).status_code == 400
    projects = client.get("/api/v1/projects", params={"limit": 1}).json()
    assert len(projects["items"]) == 1 and projects["next_cursor"]


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
