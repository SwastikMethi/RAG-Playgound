import asyncio

import httpx
import pytest
from tests.integration.test_api import client as client
from reportlab.pdfgen.canvas import Canvas

from rag_runtime.pageindex_build import build_document
from rag_runtime.providers import Gateway, Profile, empty_usage
from rag_runtime.errors import Problem
from tests.unit.test_runtime import source

pytestmark = pytest.mark.integration


def pdf_fixture(tmp_path):
    path = tmp_path / "clock.pdf"
    canvas = Canvas(str(path))
    canvas.setFont("Helvetica-Bold", 20)
    canvas.drawString(50, 760, "Clock Recovery")
    canvas.setFont("Helvetica", 12)
    canvas.drawString(
        50, 725, "NEBULA-42 means clock drift. Synchronize the system clock before reconnecting."
    )
    canvas.save()
    src = source("NEBULA-42 means clock drift. Synchronize the system clock before reconnecting.")
    src["segments"][0]["page"] = 1
    return path, src


@pytest.mark.asyncio
async def test_actual_pageindex_sdk_builds_and_maps_pdf_through_bounded_model_gateway(tmp_path):
    calls = []

    class SummaryBoundary:
        async def complete(self, profile, messages, **kwargs):
            calls.append(messages)
            return dict(
                text="A guide to fixing NEBULA-42 clock drift by synchronizing the system clock.",
                usage=empty_usage(),
                wait_ms=0,
                recording=dict(operation="completion", usage=empty_usage()),
            )

    profile = Profile(
        id="index",
        label="Synthetic summary boundary",
        model="fixture",
        operations=["tree_indexing"],
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    path, src = pdf_fixture(tmp_path)
    doc = await asyncio.wait_for(build_document(path, src, profile, SummaryBoundary(), root=tmp_path), 60)
    assert doc["nodes"] and doc["nodes"][0]["page_start"] == 1
    assert len(doc["page_hashes"]) == 1 and calls
    assert doc["source"]["text"] == src["text"]
    assert not list(tmp_path.glob("job-*"))


@pytest.mark.asyncio
async def test_sdk_internal_retry_loop_cannot_exceed_application_retry_policy(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("TEST_TREE_KEY", "local-test-key")

    def fail(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "Fixture rate limit"})

    profile = Profile(
        id="index",
        label="Synthetic failure boundary",
        model="fixture",
        operations=["tree_indexing"],
        base_url="https://fixture.invalid/v1",
        api_key_env="TEST_TREE_KEY",
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    path, src = pdf_fixture(tmp_path)
    with pytest.raises(Problem, match="provider"):
        await asyncio.wait_for(
            build_document(path, src, profile, Gateway(transport=httpx.MockTransport(fail)), root=tmp_path),
            60,
        )
    assert len(calls) == 2
    assert not list(tmp_path.glob("job-*"))


def test_all_tree_preparation_query_events_and_shared_answer_contract(client, tmp_path):
    import json
    from uuid import uuid4
    from workers.main import Worker
    from rag_runtime.registry import defaults

    worker = Worker(client.app.state.settings)
    profile = Profile(
        id="tree-test",
        label="Synthetic tree model boundary",
        model="fixture-tree",
        kind="fixture",
        operations=["tree_indexing", "tree_selection"],
        max_output_tokens=512,
        tokenizer="cl100k_base",
    )
    client.app.state.profiles[profile.id] = profile
    worker.profiles[profile.id] = profile

    async def boundary(profile, messages, **kwargs):
        if kwargs.get("json_mode"):
            choices = json.loads(messages[1]["content"])["choices"]
            text = json.dumps(dict(ids=[choices[0]["id"]], stop=True))
        else:
            text = "Clock recovery guide."
        return dict(text=text, usage=empty_usage(), wait_ms=0, recording={})

    worker.gateway.complete = boundary
    project = client.post(
        "/api/v1/projects", json={"name": "PageIndex real SDK with synthetic model boundary"}
    ).json()["id"]
    path, _ = pdf_fixture(tmp_path)
    source = client.post(
        f"/api/v1/projects/{project}/sources/upload",
        files={"file": ("guide.pdf", path.read_bytes(), "application/pdf")},
    ).json()
    asyncio.run(worker.run_resource(source["id"]))
    corpus = client.post(
        f"/api/v1/projects/{project}/corpus-versions", json={"source_ids": [source["id"]]}
    ).json()
    config = defaults("pageindex", worker.profiles)
    config["tree"].update(selection_profile_id=profile.id, selection_model=profile.model)
    saved = client.post(
        f"/api/v1/projects/{project}/configurations", json={"name": "PageIndex", "config": config}
    )
    assert saved.status_code == 201, saved.text
    bundle = client.post(
        f"/api/v1/projects/{project}/preparations",
        headers={"Idempotency-Key": str(uuid4())},
        json={"config_id": saved.json()["id"], "corpus_version_id": corpus["id"]},
    ).json()
    asyncio.run(worker.run_resource(bundle["id"]))
    ready = client.get("/api/v1/index-bundles/" + bundle["id"]).json()
    assert ready["status"] == "ready", ready
    run = client.post(
        f"/api/v1/projects/{project}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json=dict(
            corpus_version_id=corpus["id"],
            question="How do I fix NEBULA-42?",
            lanes=[dict(config_id=saved.json()["id"], bundle_id=bundle["id"])],
        ),
    ).json()
    asyncio.run(worker.run_resource(run["id"]))
    result = client.get("/api/v1/runs/" + run["id"]).json()
    assert result["status"] == "completed", result
    lane = result["lanes"][0]
    evidence = client.get(f"/api/v1/runs/{run['id']}/lanes/{lane['id']}/evidence").json()["evidence"]
    assert evidence[0]["location"]["page_start"] == 1
    assert evidence[0]["tree_node_ids"]
    assert "Synchronize" in lane["answer"]
    assert "tree.nodes_selected" in client.get("/api/v1/runs/" + run["id"] + "/events").text
    # Compatibility applies to the whole corpus; no silently ignored text sources.
    text_src = client.post(
        f"/api/v1/projects/{project}/sources/upload",
        files={"file": ("extra.txt", "Extra source", "text/plain")},
    ).json()
    asyncio.run(worker.run_resource(text_src["id"]))
    mixed = client.post(
        f"/api/v1/projects/{project}/corpus-versions", json={"source_ids": [source["id"], text_src["id"]]}
    ).json()
    rejected = client.post(
        f"/api/v1/projects/{project}/preparations",
        headers={"Idempotency-Key": str(uuid4())},
        json=dict(config_id=saved.json()["id"], corpus_version_id=mixed["id"]),
    )
    assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "UNSUPPORTED_CORPUS"
    worker.close()
