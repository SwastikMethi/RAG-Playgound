from fastapi import APIRouter, Request
from sqlalchemy import select

from rag_runtime.errors import Problem
from rag_runtime.providers import empty_usage
from rag_runtime.trace import empty_timing
from workers.events import persist_event
from .database import scoped
from .models import Export, IndexBundle, Job, Lane, Run, RunEvent, Source
from .present import present
from .runs import TERMINAL, lane_in_run

router = APIRouter(prefix="/api/v1")


def request_cancel(store, s, run_id, lane_id=None):
    run = scoped(s, Run, run_id)
    job = s.scalar(
        select(Job)
        .where(Job.kind == "compare_run", Job.resource_id == run.id, Job.project_id == run.project_id)
        .with_for_update()
    )
    run = scoped(s, Run, run_id, lock=True)
    if lane_id:
        lane_in_run(s, run.id, lane_id)
    if run.status in TERMINAL:
        return run
    lanes = list(s.scalars(select(Lane).where(Lane.run_id == run.id).order_by(Lane.created_at, Lane.id)))
    now = store.now(s)
    if lane_id is None:
        run.cancel_requested_at = now
        job.cancel_requested_at = now
    last = (
        s.scalar(
            select(RunEvent.elapsed_ms)
            .where(RunEvent.run_id == run.id)
            .order_by(RunEvent.seq.desc())
            .limit(1)
        )
        or 0
    )
    for lane in lanes:
        if lane.status in TERMINAL or (lane_id and lane.id != lane_id):
            continue
        lane.cancel_requested_at = now
        if lane.status == "queued":
            persist_event(
                s,
                store,
                run,
                lane.id,
                "lane.cancelled",
                dict(reason="Cancelled before starting.", metrics=empty_timing(), usage=empty_usage()),
                last,
            )
    if all(lane.status in TERMINAL for lane in lanes):
        status = (
            "cancelled"
            if all(lane.status == "cancelled" for lane in lanes)
            else "partial"
            if any(lane.status == "completed" for lane in lanes)
            else "failed"
        )
        persist_event(
            s,
            store,
            run,
            None,
            "run." + status,
            dict(status=status, lane_ids=[lane.id for lane in lanes]),
            last,
        )
        job.status, job.completed_at = "cancelled", now
    return run


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str, request: Request):
    store = request.state.store
    with store.session() as s:
        run = request_cancel(store, s, run_id)
        return dict(run_id=run_id, lane_id=None, cancel_requested=bool(run.cancel_requested_at))


@router.post("/runs/{run_id}/lanes/{lane_id}/cancel", status_code=202)
def cancel_lane(run_id: str, lane_id: str, request: Request):
    store = request.state.store
    with store.session() as s:
        request_cancel(store, s, run_id, lane_id)
        _, lane = lane_in_run(s, run_id, lane_id)
        return dict(run_id=run_id, lane_id=lane_id, cancel_requested=bool(lane.cancel_requested_at))


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str, request: Request):
    store = request.state.store
    with store.session() as s:
        job = scoped(s, Job, job_id, lock=True)
        if job.kind == "delete_source":
            raise Problem("UNSUPPORTED_CANCEL", "A confirmed deletion must finish its cleanup.", 409)
        if job.status not in {"queued", "running"}:
            return present(s, job)
        if job.kind == "compare_run":
            request_cancel(store, s, job.resource_id)
        else:
            job.cancel_requested_at = store.now(s)
            if job.status == "queued":
                job.status, job.completed_at = "cancelled", store.now(s)
                error = Problem("CANCELLED", "Cancelled before starting.").public()
                model = {"ingest_source": Source, "prepare_index": IndexBundle, "export_lane": Export}[
                    job.kind
                ]
                resource = scoped(s, model, job.resource_id, job.project_id)
                resource.status, resource.error = "failed", error
                job.error = error
        return present(s, job)
