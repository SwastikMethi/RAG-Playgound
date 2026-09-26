import asyncio
from uuid import uuid4

import pytest

from tests.integration.test_api import client as client

pytestmark = pytest.mark.integration


def test_dense_hybrid_and_real_reranker_share_preparation_but_embed_queries_independently(client):
    from workers.main import Worker

    worker = Worker(client.app.state.settings)
    calls = []
    embed = worker.gateway.embed

    async def track(profile, inputs):
        calls.append(inputs)
        return await embed(profile, inputs)

    worker.gateway.embed = track
    project = client.post("/api/v1/projects", json={"name": "Hybrid comparison"}).json()["id"]
    src = client.post(
        f"/api/v1/projects/{project}/sources/upload",
        files={
            "file": (
                "guide.md",
                "# Clock\nNEBULA-42 means clock drift. Synchronize the system clock.\n\n# Gardens\nApples grow on trees.",
                "text/markdown",
            )
        },
    ).json()
    asyncio.run(worker.run_once(src["job_id"]))
    corpus = client.post(
        f"/api/v1/projects/{project}/corpus-versions", json={"source_ids": [src["id"]]}
    ).json()
    capabilities = client.get("/api/v1/system/capabilities").json()["items"]
    lanes = []
    for technique in ["dense", "hybrid", "hybrid_rerank"]:
        config = next(c for c in capabilities if c["technique"] == technique)["default_config"]
        assert config["reranker"] is None or config["reranker"]["model_revision"]
        saved = client.post(
            f"/api/v1/projects/{project}/configurations", json={"name": technique, "config": config}
        ).json()
        response = client.post(
            f"/api/v1/projects/{project}/preparations",
            headers={"Idempotency-Key": str(uuid4())},
            json={"config_id": saved["id"], "corpus_version_id": corpus["id"]},
        )
        assert response.status_code == 202, response.text
        bundle = response.json()
        if bundle["job_id"]:
            asyncio.run(worker.run_once(bundle["job_id"]))
        bundle = client.get("/api/v1/index-bundles/" + bundle["id"]).json()
        assert bundle["status"] == "ready", bundle
        assert bundle["preparation_reused"] == (technique != "dense")
        lanes.append(dict(config_id=saved["id"], bundle_id=bundle["id"]))
    assert len(calls) == 1
    calls.clear()
    response = client.post(
        f"/api/v1/projects/{project}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json=dict(corpus_version_id=corpus["id"], question="How do I fix clock drift?", lanes=lanes),
    )
    assert response.status_code == 202, response.text
    run = response.json()
    asyncio.run(worker.run_resource(run["id"]))
    result = client.get("/api/v1/runs/" + run["id"]).json()
    assert result["status"] == "completed", result
    assert len(calls) == 3
    assert all(lane["usage"]["embedding_tokens"] > 0 for lane in result["lanes"])
    events = client.get("/api/v1/runs/" + run["id"] + "/events").text
    assert '"rerank.completed"' in events and '"branch_ranks"' in events
    original_stream = worker.gateway.stream
    generation_calls = 0

    async def fail_one(profile, config, messages):
        nonlocal generation_calls
        generation_calls += 1
        if generation_calls == 1:
            from rag_runtime.errors import Problem

            raise Problem("PROVIDER_AUTH", "The provider rejected this lane.")
        async for frame in original_stream(profile, config, messages):
            yield frame

    worker.gateway.stream = fail_one
    second = client.post(
        f"/api/v1/projects/{project}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json=dict(corpus_version_id=corpus["id"], question="How do I fix clock drift?", lanes=lanes[:2]),
    ).json()
    asyncio.run(worker.run_resource(second["id"]))
    second = client.get("/api/v1/runs/" + second["id"]).json()
    assert second["status"] == "partial"
    assert sorted(lane["status"] for lane in second["lanes"]) == ["completed", "failed"]
    worker.close()
