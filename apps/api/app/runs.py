import asyncio
import json
import time

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from rag_runtime import __version__
from rag_runtime.chunking import token_count
from rag_runtime.context import GROUNDING
from rag_runtime.contracts import digest, request as check_request, validate
from rag_runtime.errors import Problem
from rag_runtime.providers import empty_usage
from rag_runtime.registry import check_config, preparation_identity
from rag_runtime.trace import empty_timing
from .content import idempotent, remember
from .database import scoped
from .models import (
    Artifact,
    Configuration,
    Corpus,
    CorpusSource,
    Feedback,
    IndexBundle,
    Job,
    Lane,
    Preference,
    Project,
    Run,
    RunEvent,
    Source,
)
from .present import page_records, present

router = APIRouter(prefix="/api/v1")
TERMINAL = {"completed", "partial", "failed", "cancelled", "timed_out"}


def lane_in_run(s, run_id, lane_id):
    run = scoped(s, Run, run_id)
    lane = s.scalar(select(Lane).where(Lane.id == lane_id, Lane.run_id == run.id))
    if lane is None:
        raise Problem("NOT_FOUND", "This lane does not belong to the selected run.", 404)
    return run, lane


def provenance(s, corpus, bundle, config, profiles):
    gen, emb, tree = config["generation"], config["embedding"], config["tree"]
    fingerprints = dict(
        generation=profiles[gen["profile_id"]].fingerprint(),
        embedding=profiles[emb["profile_id"]].fingerprint() if emb else None,
        tree_indexing=profiles[tree["index_profile_id"]].fingerprint() if tree else None,
        tree_selection=profiles[tree["selection_profile_id"]].fingerprint() if tree else None,
    )
    sources = s.scalars(
        select(Source)
        .join(CorpusSource)
        .where(CorpusSource.corpus_version_id == corpus.id, Source.project_id == corpus.project_id)
    )
    return dict(
        runtime_revision=__version__,
        prompt_sha256=digest(GROUNDING.encode()),
        profile_fingerprints=fingerprints,
        model_revisions=dict(
            generation=None,
            embedding=None,
            reranker=config["reranker"]["model_revision"] if config["reranker"] else None,
            tree_indexing=None,
            tree_selection=None,
        ),
        parser_revisions=[
            dict(
                source_id=src.id,
                parser=src.source_metadata["parser"],
                revision=src.source_metadata["parser_revision"],
            )
            for src in sources
        ],
        artifact_ids=bundle.artifact_ids,
        cache_state="unknown",
    )


@router.post("/projects/{project_id}/runs", status_code=202)
def create_run(project_id: str, body: dict, request: Request, idempotency_key: str | None = Header(None)):
    check_request(body, "CreateRun")
    if not body["question"].strip():
        raise Problem("VALIDATION_ERROR", "Enter a question.")
    store, profiles = request.app.state.store, request.app.state.profiles
    with store.session() as s:
        scoped(s, Project, project_id, lock=True)
        prior = idempotent(store, s, project_id, "run", idempotency_key, body)
        if prior:
            return present(s, scoped(s, Run, prior, project_id))
        corpus = scoped(s, Corpus, body["corpus_version_id"], project_id)
        from .deletion import require_corpus_ready

        require_corpus_ready(s, corpus)
        if body.get("parent_run_id"):
            scoped(s, Run, body["parent_run_id"], project_id)
        lanes, common = [], None
        for selected in body["lanes"]:
            config = scoped(s, Configuration, selected["config_id"], project_id)
            bundle = scoped(s, IndexBundle, selected["bundle_id"], project_id)
            check_config(config.config, profiles)
            if (
                bundle.status != "ready"
                or bundle.corpus_version_id != corpus.id
                or bundle.config_id != config.id
                or bundle.requirements_sha256
                != preparation_identity(config.config, corpus.content_fingerprint, profiles)
            ):
                raise Problem(
                    "INDEX_NOT_READY",
                    "Prepare each selected configuration for this corpus and current model profiles.",
                    409,
                )
            generation = config.config["generation"]
            if common is not None and generation != common:
                raise Problem(
                    "GENERATION_MISMATCH",
                    "Align generation settings across lanes for a controlled comparison.",
                )
            common = generation
            p = profiles[generation["profile_id"]]
            if (
                token_count(GROUNDING + body["question"], p.tokenizer)
                + generation["context_budget_tokens"]
                + generation["max_output_tokens"]
                + 64
                > p.max_input_tokens
            ):
                raise Problem(
                    "MODEL_INPUT_LIMIT",
                    "The question and configured context exceed the generation model's limit.",
                )
            lanes.append((config, bundle))
        run = Run(
            mode=request.app.state.settings.mode,
            project_id=project_id,
            corpus_version_id=corpus.id,
            question=body["question"],
            parent_run_id=body.get("parent_run_id"),
            created_at=store.now(s),
        )
        s.add(run)
        s.flush()
        for config, bundle in lanes:
            s.add(
                Lane(
                    run_id=run.id,
                    config_id=config.id,
                    bundle_id=bundle.id,
                    config_snapshot=config.config,
                    provenance=provenance(s, corpus, bundle, config.config, profiles),
                    metrics=empty_timing(),
                    usage=empty_usage(),
                )
            )
        s.add(Job(project_id=project_id, kind="compare_run", resource_id=run.id))
        remember(store, s, project_id, "run", idempotency_key, body, run.id)
        s.flush()
        return present(s, run)


@router.get("/runs/{run_id}")
def run(run_id: str, request: Request):
    with request.app.state.store.session() as s:
        return present(s, scoped(s, Run, run_id))


@router.get("/projects/{project_id}/runs")
def history(
    project_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
    q: str = Query("", max_length=8000),
    status: str | None = None,
):
    with request.app.state.store.session() as s:
        scoped(s, Project, project_id)
        query = select(Run).where(Run.project_id == project_id)
        if status:
            if status not in TERMINAL | {"queued", "running"}:
                raise Problem("VALIDATION_ERROR", "Unknown run status.")
            query = query.where(Run.status == status)
        if q:
            query = query.where(Run.question.contains(q, autoescape=True))
        return page_records(s, query, Run, limit, cursor, descending=True)


def event_dict(row):
    return dict(
        schema_version="1.0.0",
        event_id=row.event_id,
        run_id=row.run_id,
        lane_id=row.lane_id,
        seq=row.seq,
        emitted_at=row.emitted_at.isoformat(),
        elapsed_ms=row.elapsed_ms,
        type=row.type,
        payload=row.payload,
    )


@router.get("/runs/{run_id}/events")
async def events(
    run_id: str,
    request: Request,
    after_seq: int | None = Query(None, ge=0),
    last_event_id: str | None = Header(None),
):
    store = request.app.state.store
    cursor = after_seq or 0
    if last_event_id:
        try:
            owner, value = last_event_id.rsplit(":", 1)
            value = int(value)
            if owner != run_id or value < 0 or (after_seq is not None and value != after_seq):
                raise ValueError()
            cursor = value
        except ValueError:
            raise Problem("INVALID_CURSOR", "SSE cursors must agree and belong to this run.", 400) from None
    with store.session() as s:
        run = scoped(s, Run, run_id)
        if cursor > run.last_seq:
            raise Problem("INVALID_CURSOR", "The event cursor is beyond this run's saved history.", 400)

    async def frames():
        nonlocal cursor
        heartbeat = time.monotonic()
        while not await request.is_disconnected():
            with store.session() as s:
                run = scoped(s, Run, run_id)
                terminal = run.status in TERMINAL
                rows = list(
                    s.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == run.id, RunEvent.seq > cursor)
                        .order_by(RunEvent.seq)
                        .limit(200)
                    )
                )
                frames = [event_dict(row) for row in rows]
            for frame in frames:
                cursor = frame["seq"]
                yield f"id: {run_id}:{cursor}\nevent: trace\ndata: {json.dumps(frame, ensure_ascii=False)}\n\n"
            if terminal and len(frames) < 200:
                return
            if time.monotonic() - heartbeat >= 15:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.25)

    return StreamingResponse(frames(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.get("/runs/{run_id}/lanes/{lane_id}/evidence")
def evidence(run_id: str, lane_id: str, request: Request):
    with request.app.state.store.session() as s:
        _, lane = lane_in_run(s, run_id, lane_id)
        return validate(
            dict(run_id=run_id, lane_id=lane_id, evidence=lane.evidence), "openapi.yaml", "EvidenceList"
        )


@router.put("/runs/{run_id}/lanes/{lane_id}/feedback")
def feedback(run_id: str, lane_id: str, body: dict, request: Request):
    check_request(body, "Feedback")
    with request.app.state.store.session() as s:
        lane_in_run(s, run_id, lane_id)
        row = s.get(Feedback, lane_id) or Feedback(run_id=run_id, lane_id=lane_id)
        row.helpful, row.note = body["helpful"], body["note"]
        row.updated_at = request.app.state.store.now(s)
        s.add(row)
        return body


@router.put("/runs/{run_id}/preference")
def preference(run_id: str, body: dict, request: Request):
    check_request(body, "Preference")
    if body["preferred_lane_id"] and body["tied_lane_ids"]:
        raise Problem("VALIDATION_ERROR", "Choose one preferred lane or a tie.")
    with request.app.state.store.session() as s:
        scoped(s, Run, run_id, lock=True)
        for id in [body["preferred_lane_id"]] if body["preferred_lane_id"] else body["tied_lane_ids"]:
            lane_in_run(s, run_id, id)
        row = s.get(Preference, run_id) or Preference(run_id=run_id)
        for key, value in body.items():
            setattr(row, key, value)
        row.updated_at = request.app.state.store.now(s)
        s.add(row)
        return body


@router.get("/runs/{run_id}/lanes/{lane_id}/artifacts/{artifact_id}")
def trace_artifact(run_id: str, lane_id: str, artifact_id: str, request: Request):
    store = request.app.state.store
    with store.session() as s:
        run, lane = lane_in_run(s, run_id, lane_id)
        artifact = scoped(s, Artifact, artifact_id, run.project_id)
        if artifact.kind != "step_details" or artifact.manifest.get("lane_id") != lane.id:
            raise Problem("NOT_FOUND", "The artifact does not belong to this lane.", 404)
        return dict(
            id=artifact.id, kind="step_details", data=json.loads(store.read(s, artifact.id, run.project_id))
        )
