import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Artifact, Source, IndexBundle
from rag_runtime.errors import Problem
from rag_runtime.vectors import Scope
from tests.integration.test_api import client as client
from tests.integration.test_export import completed_lane, export_lane

pytestmark = pytest.mark.integration


def test_busy_confirmation_retry_and_complete_scoped_cascade(client, monkeypatch):
    worker, run, _ = completed_lane(client, "dense")
    project = run["project_id"]
    source_id = client.get("/api/v1/corpus-versions/" + run["corpus_version_id"]).json()["source_ids"][0]
    export, _ = export_lane(client, worker, run, include_data=True)
    with worker.store.session() as s:
        bundle = s.get(IndexBundle, run["lanes"][0]["bundle_id"])
        prepared = json.loads(worker.store.read(s, bundle.artifact_ids[0], project))
        old_paths = [
            worker.store.path(a) for a in s.scalars(select(Artifact).where(Artifact.project_id == project))
        ]
    survivor = client.post(
        f"/api/v1/projects/{project}/sources/upload",
        files={"file": ("keep.txt", "Keep this unrelated source", "text/plain")},
    ).json()
    asyncio.run(worker.run_resource(survivor["id"]))
    queued = client.post(
        f"/api/v1/projects/{project}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "corpus_version_id": run["corpus_version_id"],
            "question": "NEBULA-42",
            "lanes": [{"config_id": run["lanes"][0]["config_id"], "bundle_id": run["lanes"][0]["bundle_id"]}],
        },
    ).json()
    route = f"/api/v1/sources/{source_id}"
    impact = client.get(route + "/impact")
    assert impact.status_code == 200, impact.text
    assert (
        impact.json()["run_count"] == 2
        and impact.json()["export_count"] == 1
        and impact.json()["active_job_ids"]
    )
    assert (
        client.delete(route, params={"cascade": True, "confirmation_source_id": "wrong"}).status_code == 422
    )
    params = {"cascade": True, "confirmation_source_id": source_id}
    busy = client.delete(route, params=params)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "RESOURCE_BUSY"
    client.post("/api/v1/runs/" + queued["id"] + "/cancel")
    original = worker.vector_store().delete

    async def unavailable(*args, **kwargs):
        raise Problem("VECTOR_UNAVAILABLE", "The vector service is unavailable.")

    monkeypatch.setattr(worker.vectors, "delete", unavailable)
    deleting = client.delete(route, params=params)
    assert deleting.status_code == 202, deleting.text
    asyncio.run(worker.run_once(deleting.json()["job_id"]))
    failed = client.get(route).json()
    assert failed["status"] == "deleting" and failed["error"]
    # New work must not race the confirmed cascade, even while cleanup is retryable.
    denied = client.post(
        f"/api/v1/projects/{project}/preparations",
        headers={"Idempotency-Key": str(uuid4())},
        json={"corpus_version_id": run["corpus_version_id"], "config_id": run["lanes"][0]["config_id"]},
    )
    assert denied.status_code == 409
    monkeypatch.setattr(worker.vectors, "delete", original)
    retry = client.delete(route, params=params)
    assert retry.status_code == 202, retry.text
    asyncio.run(worker.run_once(retry.json()["job_id"]))
    tombstone = client.get(route).json()
    assert (
        tombstone["status"] == "deleted"
        and tombstone["metadata"] == {}
        and tombstone["display_name"] == "Deleted source"
    )
    assert client.get(route + "/file").status_code == 404
    assert client.get("/api/v1/runs/" + run["id"]).status_code == 404
    assert client.get(export["download_url"]).status_code == 404
    assert all(not path.exists() for path in old_paths)
    assert not worker.cache
    assert not asyncio.run(
        worker.vectors.search(
            Scope(**prepared["scope"]),
            prepared["vectors"][0],
            20,
            {"mode": "exact", "hnsw_ef": 128, "min_score": None},
        )
    )
    assert (
        client.get("/api/v1/sources/" + survivor["id"] + "/content").json()["content"]
        == "Keep this unrelated source"
    )
    with worker.store.session() as s:
        assert s.get(Source, survivor["id"]).status == "ready"
        assert not list(s.scalars(select(IndexBundle).where(IndexBundle.project_id == project)))
    worker.close()


def test_expired_preparation_vectors_are_reconciled_without_touching_ready_scope(client):
    from datetime import timedelta
    from app.models import Job

    worker, run, _ = completed_lane(client, "dense")
    with worker.store.session() as s:
        bundle = s.get(IndexBundle, run["lanes"][0]["bundle_id"])
        prepared = json.loads(worker.store.read(s, bundle.artifact_ids[0], run["project_id"]))
        stale = dict(prepared["scope"], variant_fingerprint=uuid4().hex)
        job = Job(
            project_id=run["project_id"],
            kind="prepare_index",
            resource_id=uuid4().hex,
            status="failed",
            completed_at=worker.store.now(s) - timedelta(seconds=120),
            progress={"vector_scope": stale, "vector_dimensions": 64},
        )
        s.add(job)
        s.flush()
        job_id = job.id
    asyncio.run(worker.vectors.put(Scope(**stale), prepared["chunks"], prepared["vectors"], 64))
    worker.last_vector_cleanup = 0
    asyncio.run(worker.reconcile())
    search = {"mode": "exact", "hnsw_ef": 128, "min_score": None}
    assert not asyncio.run(worker.vectors.search(Scope(**stale), prepared["vectors"][0], 20, search))
    assert asyncio.run(worker.vectors.search(Scope(**prepared["scope"]), prepared["vectors"][0], 20, search))
    with worker.store.session() as s:
        assert s.get(Job, job_id).progress["vector_cleanup_done"]
    worker.close()
