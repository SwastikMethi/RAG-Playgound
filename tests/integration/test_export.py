import asyncio
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from rag_runtime.contracts import digest, validate
from tests.integration.test_api import client as client

pytestmark = pytest.mark.integration


def completed_lane(client, technique):
    from workers.main import Worker

    worker = Worker(client.app.state.settings)
    project = client.post("/api/v1/projects", json={"name": "Private export project"}).json()["id"]
    text = "# Private clock guide\nNEBULA-42 means clock drift. Synchronize the clock. 🪐"
    source = client.post(
        f"/api/v1/projects/{project}/sources/upload",
        files={"file": ("confidential-original-name.md", text, "text/markdown")},
    ).json()
    asyncio.run(worker.run_resource(source["id"]))
    corpus = client.post(
        f"/api/v1/projects/{project}/corpus-versions", json={"source_ids": [source["id"]]}
    ).json()
    capabilities = client.get("/api/v1/system/capabilities").json()["items"]
    config = next(c["default_config"] for c in capabilities if c["technique"] == technique)
    cfg = client.post(
        f"/api/v1/projects/{project}/configurations", json={"name": technique, "config": config}
    ).json()
    bundle = client.post(
        f"/api/v1/projects/{project}/preparations",
        headers={"Idempotency-Key": str(uuid4())},
        json={"config_id": cfg["id"], "corpus_version_id": corpus["id"]},
    ).json()
    asyncio.run(worker.run_resource(bundle["id"]))
    assert client.get("/api/v1/index-bundles/" + bundle["id"]).json()["status"] == "ready"
    run = client.post(
        f"/api/v1/projects/{project}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "corpus_version_id": corpus["id"],
            "question": "What does NEBULA-42 mean?",
            "lanes": [{"config_id": cfg["id"], "bundle_id": bundle["id"]}],
        },
    ).json()
    asyncio.run(worker.run_resource(run["id"]))
    run = client.get("/api/v1/runs/" + run["id"]).json()
    assert run["lanes"][0]["status"] == "completed", run
    return worker, run, text


def export_lane(client, worker, run, include_data=False):
    lane = run["lanes"][0]
    route = f"/api/v1/runs/{run['id']}/lanes/{lane['id']}/exports"
    headers = {"Idempotency-Key": str(uuid4())}
    body = {"include_data": include_data, "verification_mode": "offline"}
    response = client.post(route, headers=headers, json=body)
    assert response.status_code == 202, response.text
    item = response.json()
    assert client.post(route, headers=headers, json=body).json()["id"] == item["id"]
    asyncio.run(worker.run_resource(item["id"]))
    item = client.get("/api/v1/exports/" + item["id"]).json()
    assert item["status"] == "ready", item
    validate(item["manifest"], "export-manifest.schema.json")
    assert item["manifest"]["verification"]["offline_replay"]["status"] == "passed"
    assert item["manifest"]["verification"]["live_replay"]["status"] == "not_run"
    response = client.get(item["download_url"])
    assert response.status_code == 200
    return item, response.content


@pytest.mark.parametrize("technique", ["bm25", "dense", "hybrid", "hybrid_rerank", "parent_child"])
def test_all_chunk_adapter_exports_are_private_and_replay_the_shared_runtime(client, technique):
    worker, run, text = completed_lane(client, technique)
    try:
        item, content = export_lane(client, worker, run)
        archive = zipfile.ZipFile(io.BytesIO(content))
        names = archive.namelist()
        assert all(not n.startswith(("/", "data/")) and ".." not in Path(n).parts for n in names)
        assert {
            "manifest.json",
            "pipeline.json",
            "uv.lock",
            "scripts/query.py",
            "scripts/ingest.py",
            "app/main.py",
            "src/rag_runtime/runtime.py",
        } <= set(names)
        all_content = b"\n".join(archive.read(name) for name in names)
        for forbidden in [
            text,
            "confidential-original-name.md",
            run["question"],
            run["lanes"][0]["answer"],
        ]:
            assert forbidden.encode() not in all_content
        assert (
            archive.read("src/rag_runtime/runtime.py") == Path("packages/rag_runtime/runtime.py").read_bytes()
        )
        assert digest(archive.read("uv.lock")) == item["manifest"]["dependency_lock_sha256"]
    finally:
        worker.close()


def test_include_data_commands_hash_guard_and_tampered_recording_fails_closed(client, tmp_path):
    from app.models import Artifact, Lane
    from sqlalchemy import select

    worker, run, text = completed_lane(client, "bm25")
    try:
        item, content = export_lane(client, worker, run, include_data=True)
        evidence_dir = Path("test-results")
        evidence_dir.mkdir(exist_ok=True)
        (evidence_dir / "export-included-fixture.zip").write_bytes(content)
        target = tmp_path / "standalone"
        zipfile.ZipFile(io.BytesIO(content)).extractall(target)
        assert text.encode() in b"".join(p.read_bytes() for p in (target / "data").iterdir())
        env = dict(os.environ, PYTHONPATH=str(target / "src"))
        for args in [
            ("scripts/verify.py",),
            ("scripts/ingest.py", "--source-dir", "data"),
            ("scripts/query.py", "What does NEBULA-42 mean?"),
        ]:
            result = subprocess.run(
                [sys.executable, *args], cwd=target, env=env, capture_output=True, text=True, timeout=60
            )
            assert result.returncode == 0, result.stdout + result.stderr
        answer = json.loads(result.stdout)
        assert answer["answer"] == run["lanes"][0]["answer"]
        assert answer["evidence"][0]["source_name"].startswith("source-")
        path = next((target / "data").iterdir())
        path.write_text("changed source")
        result = subprocess.run(
            [sys.executable, "scripts/ingest.py", "--source-dir", "data"],
            cwd=target,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0 and "SOURCE_HASH_MISMATCH" in result.stdout
        with worker.store.session() as s:
            lane = s.get(Lane, run["lanes"][0]["id"])
            artifact = s.scalar(
                select(Artifact).where(
                    Artifact.id.in_(lane.provenance["artifact_ids"]), Artifact.kind == "boundary_recordings"
                )
            )
            records = json.loads(worker.store.read(s, artifact.id, run["project_id"]))
            next(r for r in records if r["operation"] == "generation")["request_sha256"] = "0" * 64
            replacement = worker.store.put(
                s, run["project_id"], "boundary_recordings", json.dumps(records).encode()
            )
            lane.provenance = dict(
                lane.provenance,
                artifact_ids=[
                    i if i != artifact.id else replacement.id for i in lane.provenance["artifact_ids"]
                ],
            )
        response = client.post(
            f"/api/v1/runs/{run['id']}/lanes/{run['lanes'][0]['id']}/exports",
            headers={"Idempotency-Key": str(uuid4())},
            json={"include_data": False, "verification_mode": "offline"},
        ).json()
        asyncio.run(worker.run_resource(response["id"]))
        failed = client.get("/api/v1/exports/" + response["id"]).json()
        assert failed["status"] == "failed" and failed["download_url"] is None
    finally:
        worker.close()
