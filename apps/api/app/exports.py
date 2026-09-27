"""Exports are protected, queued builds tied to one immutable completed lane."""

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from rag_runtime.contracts import request as check_request
from rag_runtime.errors import Problem
from .content import idempotent, remember
from .database import scoped
from .models import Artifact, Corpus, Export, Job, Lane, Project, Run
from .present import present

router = APIRouter(prefix="/api/v1")


@router.post("/runs/{run_id}/lanes/{lane_id}/exports", status_code=202)
def create_export(
    run_id: str, lane_id: str, body: dict, request: Request, idempotency_key: str | None = Header(None)
):
    check_request(body, "ExportRequest")
    if body["verification_mode"] == "live" and request.app.state.settings.mode != "live":
        raise Problem(
            "LIVE_UNAVAILABLE",
            "Live verification requires live provider profiles. Fixture demonstrations can only be checked offline.",
            409,
        )
    store = request.app.state.store
    with store.session() as s:
        run = scoped(s, Run, run_id)
        if body["verification_mode"] == "live" and run.mode != "live":
            raise Problem(
                "LIVE_UNAVAILABLE",
                "This saved run is a fixture demonstration. Its export can only be verified offline.",
                409,
            )
        scoped(s, Project, run.project_id, lock=True)
        from .deletion import require_corpus_ready

        require_corpus_ready(s, scoped(s, Corpus, run.corpus_version_id, run.project_id))
        lane = s.scalar(select(Lane).where(Lane.id == lane_id, Lane.run_id == run_id))
        if not lane:
            raise Problem("NOT_FOUND", "The lane is not part of this run.", 404)
        operation = "export:" + lane_id
        previous = idempotent(store, s, run.project_id, operation, idempotency_key, body)
        if previous:
            return present(s, scoped(s, Export, previous, run.project_id))
        if lane.status != "completed":
            raise Problem("LANE_NOT_COMPLETE", "Export requires a completed lane.", 409)
        item = Export(project_id=run.project_id, run_id=run.id, lane_id=lane.id, **body)
        s.add(item)
        s.flush()
        job = Job(project_id=run.project_id, kind="export_lane", resource_id=item.id)
        s.add(job)
        s.flush()
        item.job_id = job.id
        remember(store, s, run.project_id, operation, idempotency_key, body, item.id)
        return present(s, item)


@router.get("/exports/{export_id}")
def get_export(export_id: str, request: Request):
    with request.app.state.store.session() as s:
        return present(s, scoped(s, Export, export_id))


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, request: Request):
    store = request.app.state.store
    with store.session() as s:
        item = scoped(s, Export, export_id)
        if item.status != "ready" or not item.artifact_id:
            raise Problem("EXPORT_NOT_READY", "This export is not ready for download.", 409)
        artifact = scoped(s, Artifact, item.artifact_id, item.project_id)
        return FileResponse(
            store.path(artifact), media_type="application/zip", filename="rag-implementation.zip"
        )
