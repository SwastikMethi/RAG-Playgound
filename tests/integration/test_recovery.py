import asyncio
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Job, RunEvent
from rag_runtime.errors import Problem
from tests.integration.test_api import client as client

pytestmark = pytest.mark.integration


@pytest.fixture
def prepared(client):
    from workers.main import Worker

    worker = Worker(client.app.state.settings)
    project = client.post("/api/v1/projects", json={"name": "Recovery"}).json()["id"]
    src = client.post(
        f"/api/v1/projects/{project}/sources/upload",
        files={"file": ("text.txt", "Clock drift is fixed by synchronizing the clock.", "text/plain")},
    ).json()
    asyncio.run(worker.run_once(src["job_id"]))
    corpus = client.post(
        f"/api/v1/projects/{project}/corpus-versions", json={"source_ids": [src["id"]]}
    ).json()
    cfg = client.get("/api/v1/system/capabilities").json()["items"][0]["default_config"]
    cfg["limits"]["lane_timeout_ms"] = 1000
    config = client.post(
        f"/api/v1/projects/{project}/configurations", json={"name": "BM25", "config": cfg}
    ).json()
    bundle = client.post(
        f"/api/v1/projects/{project}/preparations",
        headers={"Idempotency-Key": str(uuid4())},
        json={"corpus_version_id": corpus["id"], "config_id": config["id"]},
    ).json()
    asyncio.run(worker.run_once(bundle["job_id"]))

    def create(lane_count=1):
        response = client.post(
            f"/api/v1/projects/{project}/runs",
            headers={"Idempotency-Key": str(uuid4())},
            json=dict(
                corpus_version_id=corpus["id"],
                question="How do I fix clock drift?",
                lanes=[dict(config_id=config["id"], bundle_id=bundle["id"])] * lane_count,
            ),
        )
        assert response.status_code == 202, response.text
        return response.json()

    yield worker, create
    worker.close()


@pytest.mark.asyncio
async def test_five_lanes_share_one_cancellation_poll_and_cancel_independently(client, prepared):
    from sqlalchemy import event
    from app.models import Lane

    worker, create = prepared
    run = create(5)
    with worker.store.session() as s:
        lanes = list(s.scalars(select(Lane).where(Lane.run_id == run["id"])))
        for lane in lanes:
            snapshot = deepcopy(lane.config_snapshot)
            snapshot["limits"]["lane_timeout_ms"] = 5000
            lane.config_snapshot = snapshot

    release = asyncio.Event()

    async def stream(*_args):
        yield dict(text="Partial")
        await release.wait()
        yield dict(text=" complete")

    worker.gateway.stream = stream
    ownership_reads = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM jobs" in statement and "FOR UPDATE" in statement:
            ownership_reads.append(statement)

    event.listen(worker.store.engine, "before_cursor_execute", capture)
    task = asyncio.create_task(worker.run_resource(run["id"]))
    try:
        for _ in range(200):
            saved = client.get("/api/v1/runs/" + run["id"]).json()
            if len(saved["lanes"]) == 5 and all(lane["answer"] for lane in saved["lanes"]):
                break
            await asyncio.sleep(0.02)
        assert all(lane["answer"] == "Partial" for lane in saved["lanes"])
        ownership_reads.clear()
        await asyncio.sleep(0.35)
        assert len(ownership_reads) <= 1

        cancelled = saved["lanes"][0]["id"]
        response = client.post(f"/api/v1/runs/{run['id']}/lanes/{cancelled}/cancel")
        assert response.status_code == 202, response.text
        for _ in range(150):
            saved = client.get("/api/v1/runs/" + run["id"]).json()
            if next(lane for lane in saved["lanes"] if lane["id"] == cancelled)["status"] == "cancelled":
                break
            await asyncio.sleep(0.02)
        release.set()
        await asyncio.wait_for(task, 5)
        saved = client.get("/api/v1/runs/" + run["id"]).json()
        assert next(lane for lane in saved["lanes"] if lane["id"] == cancelled)["status"] == "cancelled"
        assert all(
            lane["status"] == "completed" and lane["answer"] == "Partial complete"
            for lane in saved["lanes"]
            if lane["id"] != cancelled
        )
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        event.remove(worker.store.engine, "before_cursor_execute", capture)


def test_queued_cancellation_has_no_query_clock_or_provider_call(client, prepared):
    worker, create = prepared
    run = create()
    response = client.post(f"/api/v1/runs/{run['id']}/cancel")
    assert response.status_code == 202, response.text
    saved = client.get("/api/v1/runs/" + run["id"]).json()
    assert saved["status"] == "cancelled"
    assert saved["lanes"][0]["metrics"]["total_ms"] is None
    assert not asyncio.run(worker.run_resource(run["id"]))


@pytest.mark.asyncio
async def test_partial_answer_cancellation_closes_spans_and_stops_output(client, prepared):
    worker, create = prepared
    run = create()

    async def stream(*args):
        yield dict(text="Partial 🪐")
        await asyncio.sleep(60)
        yield dict(text=" must never appear")

    worker.gateway.stream = stream
    task = asyncio.create_task(worker.run_resource(run["id"]))
    for _ in range(100):
        saved = client.get("/api/v1/runs/" + run["id"]).json()
        if saved["lanes"][0]["answer"]:
            break
        await asyncio.sleep(0.02)
    response = client.post(f"/api/v1/runs/{run['id']}/lanes/{run['lanes'][0]['id']}/cancel")
    assert response.status_code == 202, response.text
    await asyncio.wait_for(task, 3)
    saved = client.get("/api/v1/runs/" + run["id"]).json()
    lane = saved["lanes"][0]
    assert lane["status"] == "cancelled" and lane["answer"] == "Partial 🪐"
    assert lane["metrics"]["generation_ms"] > 0 and lane["metrics"]["ttft_ms"] > 0
    assert lane["usage"]["accounting"] == "partial"
    with worker.store.session() as s:
        events = list(s.scalars(select(RunEvent).where(RunEvent.run_id == run["id"]).order_by(RunEvent.seq)))
        starts = {e.payload["span_id"] for e in events if e.type == "stage.started"}
        ends = {e.payload["span_id"] for e in events if e.type in {"stage.completed", "stage.failed"}}
        assert starts == ends
        assert events[-1].type == "run.cancelled"


def test_worker_loss_fences_old_writer_and_terminates_unfinished_spans(client, prepared):
    from workers.events import RunWriter

    worker, create = prepared
    run = create()
    with worker.store.session() as s:
        job = s.scalar(select(Job).where(Job.resource_id == run["id"]))
        job_id = job.id
    claim = worker.store.claim(job_id)
    writer = RunWriter(worker.store, claim)
    lane_id = run["lanes"][0]["id"]

    async def start():
        await writer.emit(None, "run.started", dict(lane_ids=[lane_id], queue_ms=1))
        await writer.emit(
            lane_id,
            "lane.started",
            dict(
                technique="bm25",
                config_id=run["lanes"][0]["config_id"],
                bundle_id=run["lanes"][0]["bundle_id"],
            ),
        )
        await writer.emit(
            lane_id,
            "stage.started",
            dict(
                span_id="open_span",
                stage="retrieval",
                parent_span_id=None,
                attempt=1,
                display_label="Retrieval",
            ),
        )

    asyncio.run(start())
    with worker.store.session() as s:
        job = s.get(Job, job_id)
        job.lease_expires_at = worker.store.now(s) - timedelta(seconds=1)
    asyncio.run(worker.reconcile())
    saved = client.get("/api/v1/runs/" + run["id"]).json()
    assert saved["status"] == "failed" and saved["lanes"][0]["error"]["code"] == "WORKER_LOST"
    with pytest.raises(Problem, match="lease"):
        asyncio.run(writer.emit(lane_id, "answer.delta", dict(text="late", offset_chars=0)))
    assert not asyncio.run(worker.run_resource(run["id"]))


@pytest.mark.asyncio
async def test_deadline_preserves_partial_text_and_measured_failed_stage(client, prepared):
    worker, create = prepared
    run = create()

    async def stream(*args):
        yield dict(text="Before timeout")
        await asyncio.sleep(60)

    worker.gateway.stream = stream
    await asyncio.wait_for(worker.run_resource(run["id"]), 4)
    saved = client.get("/api/v1/runs/" + run["id"]).json()["lanes"][0]
    assert saved["status"] == "timed_out" and saved["answer"] == "Before timeout"
    assert (
        saved["metrics"]["generation_ms"] > 0
        and saved["metrics"]["total_ms"] >= saved["metrics"]["generation_ms"]
    )


def test_large_candidate_detail_moves_to_protected_artifact_without_losing_answer(client, prepared):
    from workers.events import RunWriter
    from rag_runtime.chunking import chunk_source
    from tests.unit.test_runtime import source

    worker, create = prepared
    run = create()
    with worker.store.session() as s:
        job = s.scalar(select(Job).where(Job.resource_id == run["id"]))
        job_id = job.id
    claim = worker.store.claim(job_id)
    writer = RunWriter(worker.store, claim)
    lane = run["lanes"][0]
    chunks = chunk_source(source("Clock drift. " * 1000), lane["config_snapshot"]["chunking"])
    candidates = [
        dict(chunks[0], candidate_id=str(i), evidence_id=str(i), excerpt="Clock drift. " * 1000)
        for i in range(30)
    ]

    async def check():
        await writer.emit(None, "run.started", dict(lane_ids=[lane["id"]], queue_ms=1))
        await writer.emit(
            lane["id"],
            "lane.started",
            dict(technique="bm25", config_id=lane["config_id"], bundle_id=lane["bundle_id"]),
        )
        await writer.emit(
            lane["id"],
            "stage.started",
            dict(
                span_id="large",
                stage="lexical_search",
                parent_span_id=None,
                attempt=1,
                display_label="Lexical search",
            ),
        )
        await writer.emit(
            lane["id"],
            "retrieval.candidates",
            dict(span_id="large", stage="lexical_search", candidates=candidates),
        )
        await writer.emit(
            lane["id"],
            "stage.completed",
            dict(span_id="large", stage="lexical_search", duration_ms=10, resource_wait_ms=0),
        )
        await writer.emit(lane["id"], "answer.delta", dict(text="Kept 🪐", offset_chars=0))

    asyncio.run(check())
    with worker.store.session() as s:
        event = s.scalar(
            select(RunEvent).where(RunEvent.run_id == run["id"], RunEvent.type == "stage.completed")
        )
        artifact = event.payload["details"]["artifact_id"]
    response = client.get(f"/api/v1/runs/{run['id']}/lanes/{lane['id']}/artifacts/{artifact}")
    assert response.status_code == 200 and len(response.json()["data"]["payload"]["candidates"]) == 30
    assert client.get("/api/v1/runs/" + run["id"]).json()["lanes"][0]["answer"] == "Kept 🪐"
    with worker.store.session() as s:
        s.get(Job, job_id).lease_expires_at = worker.store.now(s) - timedelta(seconds=1)
    asyncio.run(worker.reconcile())


def test_coordinator_failure_finalizes_run_and_retains_partial_output(client, prepared):
    from workers.events import RunWriter

    worker, create = prepared
    run = create()

    async def crash(claim):
        writer = RunWriter(worker.store, claim)
        await writer.emit(None, "run.started", dict(lane_ids=[run["lanes"][0]["id"]], queue_ms=1))
        await writer.emit(run["lanes"][0]["id"], "answer.delta", dict(text="Retained", offset_chars=0))
        raise RuntimeError("coordinator failure")

    worker.compare = crash
    asyncio.run(worker.run_resource(run["id"]))
    saved = client.get("/api/v1/runs/" + run["id"]).json()
    assert saved["status"] == "failed" and saved["lanes"][0]["status"] == "failed"
    assert saved["lanes"][0]["answer"] == "Retained"


def test_trace_budget_still_allows_terminal_events(client, prepared):
    from workers.events import RunWriter

    worker, create = prepared
    run = create()
    with worker.store.session() as s:
        job_id = s.scalar(select(Job.id).where(Job.resource_id == run["id"]))
    writer = RunWriter(worker.store, worker.store.claim(job_id))
    lane = run["lanes"][0]

    async def check():
        await writer.emit(None, "run.started", dict(lane_ids=[lane["id"]], queue_ms=0))
        await writer.emit(lane["id"], "answer.delta", dict(text="Retained", offset_chars=0))
        writer.trace_bytes = 20 * 1024 * 1024
        await writer.emit(lane["id"], "answer.delta", dict(text=" too large", offset_chars=8))
        await asyncio.sleep(0.1)
        await writer.emit(
            lane["id"],
            "lane.failed",
            dict(
                error=Problem("TRACE_LIMIT", "Trace limit").public(),
                metrics=lane["metrics"],
                usage=lane["usage"],
            ),
        )
        await writer.emit(None, "run.failed", dict(status="failed", lane_ids=[lane["id"]]))

    asyncio.run(check())
    assert client.get("/api/v1/runs/" + run["id"]).json()["status"] == "failed"
    with worker.store.session() as s:
        s.get(Job, job_id).status = "failed"
