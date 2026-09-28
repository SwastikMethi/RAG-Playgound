import json
import re
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from rag_runtime.chunking import evidence_span
from rag_runtime.contracts import digest, request as check_request
from rag_runtime.errors import Problem
from rag_runtime.registry import check_config, preparation_identity
from .database import scoped
from .models import (
    Artifact,
    Configuration,
    Corpus,
    CorpusSource,
    IdempotencyKey,
    IndexBundle,
    Job,
    Project,
    Source,
)
from .present import page_records, present

router = APIRouter(prefix="/api/v1")


def idempotent(store, session, project, operation, key, body):
    if not key or not 8 <= len(key) <= 200:
        raise Problem("VALIDATION_ERROR", "Supply an Idempotency-Key of 8–200 characters.")
    existing = session.get(IdempotencyKey, (project, operation, digest(key)))
    if existing and existing.expires_at > store.now(session):
        if existing.request_hash != digest(body):
            raise Problem(
                "IDEMPOTENCY_CONFLICT", "This request key was already used for a different request.", 409
            )
        return existing.response_resource_id
    if existing:
        session.delete(existing)
        session.flush()
    return None


def remember(store, s, project, operation, key, body, resource_id):
    s.add(
        IdempotencyKey(
            project_id=project,
            operation=operation,
            key_hash=digest(key),
            request_hash=digest(body),
            response_resource_id=resource_id,
            expires_at=store.now(s) + timedelta(hours=24),
        )
    )


def enqueue(s, project, kind, resource):
    job = Job(project_id=project, kind=kind, resource_id=resource.id)
    s.add(job)
    s.flush()
    resource.job_id = job.id
    return job


@router.get("/projects/{project_id}/sources")
def sources(
    project_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
):
    with request.state.store.session() as s:
        scoped(s, Project, project_id)
        return page_records(s, select(Source).where(Source.project_id == project_id), Source, limit, cursor)


@router.post("/projects/{project_id}/sources/upload", status_code=202)
def upload(
    project_id: str, request: Request, file: UploadFile = File(), display_name: str | None = Form(None)
):
    name = display_name or file.filename or "source"
    if not 1 <= len(name) <= 300 or re.search(r"[\x00-\x1f/\\]", name):
        raise Problem("VALIDATION_ERROR", "Use a plain source name without paths or control characters.")
    extension = Path(file.filename or "").suffix.lower()
    kind = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown", ".txt": "text"}.get(extension)
    if not kind:
        raise Problem("UNSUPPORTED_SOURCE", "Upload a PDF, Markdown or UTF-8 text file.")
    raw = file.file.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise Problem("SOURCE_TOO_LARGE", "Each upload must be at most 20 MiB.", 413)
    if not raw or (kind == "pdf") != raw.startswith(b"%PDF-"):
        raise Problem("UNSUPPORTED_SOURCE", "File contents do not match the declared file type.")
    store = request.state.store
    with store.session() as s:
        scoped(s, Project, project_id, lock=True)
        artifact = store.put(s, project_id, "raw_source", raw, {"format": kind})
        source = Source(
            project_id=project_id,
            kind="file",
            display_name=name,
            size_bytes=len(raw),
            content_sha256=digest(raw),
            raw_artifact_id=artifact.id,
            source_metadata={"format": kind},
        )
        s.add(source)
        s.flush()
        enqueue(s, project_id, "ingest_source", source)
        return present(s, source)


@router.get("/sources/{source_id}")
def source(source_id: str, request: Request):
    with request.state.store.session() as s:
        return present(s, scoped(s, Source, source_id))


@router.get("/sources/{source_id}/content")
def source_content(
    source_id: str,
    request: Request,
    page: int | None = Query(None, ge=1),
    start_char: int = Query(0, ge=0),
    max_chars: int = Query(8000, ge=1, le=50000),
):
    store = request.state.store
    with store.session() as s:
        source = scoped(s, Source, source_id)
        if source.status != "ready":
            raise Problem("SOURCE_NOT_READY", "This source is not ready for inspection.", 409)
        parsed = json.loads(store.read(s, source.parsed_artifact_id, source.project_id))
        segment = next(
            (
                seg
                for seg in parsed["segments"]
                if (seg.get("page") == page if page else seg["start"] <= start_char < seg["end"])
            ),
            None,
        )
        if not segment:
            raise Problem("NOT_FOUND", "The requested source location does not exist.", 404)
        start = max(start_char, segment["start"])
        end = min(start + max_chars, segment["end"])
        evidence = evidence_span(parsed, start, end, segment, {})
        return dict(
            source_id=source.id,
            content=evidence["excerpt"],
            location=evidence["location"],
            truncated=end < segment["end"],
        )


@router.get("/sources/{source_id}/file")
def source_file(source_id: str, request: Request):
    store = request.state.store
    with store.session() as s:
        source = scoped(s, Source, source_id)
        if source.status != "ready" or not source.raw_artifact_id:
            raise Problem("NOT_FOUND", "The original source file is unavailable.", 404)
        artifact = scoped(s, Artifact, source.raw_artifact_id, source.project_id)
        return FileResponse(
            store.path(artifact),
            media_type="application/octet-stream",
            filename=(
                "snapshot.json"
                if source.kind == "postgres"
                else "source.pdf"
                if source.source_metadata["format"] == "pdf"
                else "source.txt"
            ),
        )


@router.post("/projects/{project_id}/corpus-versions", status_code=201)
def create_corpus(project_id: str, body: dict, request: Request):
    check_request(body, "CreateCorpus")
    with request.state.store.session() as s:
        scoped(s, Project, project_id, lock=True)
        sources = [scoped(s, Source, id, project_id) for id in body["source_ids"]]
        if any(source.status != "ready" for source in sources):
            raise Problem(
                "SOURCE_NOT_READY",
                "All selected sources must finish processing before freezing a corpus.",
                409,
            )
        if (
            sum(source.size_bytes or 0 for source in sources) > 100 * 1024 * 1024
            or sum(source.source_metadata.get("characters", 0) for source in sources) > 2_000_000
            or sum(source.source_metadata.get("pages", 0) for source in sources) > 500
        ):
            raise Problem(
                "CORPUS_TOO_LARGE", "A corpus is limited to 100 MiB, 500 pages and two million characters."
            )
        ordinal = 1 + (s.scalar(select(func.max(Corpus.ordinal)).where(Corpus.project_id == project_id)) or 0)
        corpus = Corpus(
            project_id=project_id,
            ordinal=ordinal,
            content_fingerprint=digest(
                [
                    dict(
                        id=source.id,
                        sha=source.content_sha256,
                        parser=source.source_metadata.get("parser"),
                        revision=source.source_metadata.get("parser_revision"),
                    )
                    for source in sources
                ]
            ),
        )
        s.add(corpus)
        s.flush()
        s.add_all(
            [
                CorpusSource(corpus_version_id=corpus.id, source_id=source.id, ordinal=i)
                for i, source in enumerate(sources)
            ]
        )
        s.flush()
        return present(s, corpus)


@router.get("/projects/{project_id}/corpus-versions")
def corpora(
    project_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
):
    with request.state.store.session() as s:
        scoped(s, Project, project_id)
        return page_records(
            s, select(Corpus).where(Corpus.project_id == project_id), Corpus, limit, cursor, descending=True
        )


@router.get("/corpus-versions/{corpus_version_id}")
def corpus(corpus_version_id: str, request: Request):
    with request.state.store.session() as s:
        return present(s, scoped(s, Corpus, corpus_version_id))


@router.post("/projects/{project_id}/preparations", status_code=202)
def prepare(project_id: str, body: dict, request: Request, idempotency_key: str | None = Header(None)):
    check_request(body, "PrepareRequest")
    store = request.state.store
    with store.session() as s:
        scoped(s, Project, project_id, lock=True)
        existing = idempotent(store, s, project_id, "prepare", idempotency_key, body)
        if existing:
            return present(s, scoped(s, IndexBundle, existing, project_id))
        config = scoped(s, Configuration, body["config_id"], project_id)
        corpus = scoped(s, Corpus, body["corpus_version_id"], project_id)
        from .deletion import require_corpus_ready

        require_corpus_ready(s, corpus)
        check_config(
            config.config,
            request.state.profiles,
            require_local_adapters=request.app.state.settings.deployment != "hosted",
        )
        if config.config["technique"] == "pageindex":
            sources = list(
                s.scalars(
                    select(Source)
                    .join(CorpusSource)
                    .where(CorpusSource.corpus_version_id == corpus.id, Source.project_id == project_id)
                )
            )
            if len(sources) > 10 or any(src.source_metadata.get("format") != "pdf" for src in sources):
                raise Problem(
                    "UNSUPPORTED_CORPUS", "PageIndex needs a corpus of at most ten text-layer PDFs."
                )
        identity = preparation_identity(config.config, corpus.content_fingerprint, request.state.profiles)
        prior = s.scalar(
            select(IndexBundle)
            .where(
                IndexBundle.project_id == project_id,
                IndexBundle.corpus_version_id == corpus.id,
                IndexBundle.requirements_sha256 == identity,
                IndexBundle.status == "ready",
            )
            .limit(1)
        )
        bundle = IndexBundle(
            project_id=project_id,
            corpus_version_id=corpus.id,
            config_id=config.id,
            requirements_sha256=identity,
        )
        s.add(bundle)
        s.flush()
        if prior:
            bundle.status, bundle.artifact_ids = "ready", prior.artifact_ids
            bundle.setup_metrics = dict(
                preparation_ms=prior.setup_metrics.get("preparation_ms"), preparation_reused=True
            )
        else:
            enqueue(s, project_id, "prepare_index", bundle)
        remember(store, s, project_id, "prepare", idempotency_key, body, bundle.id)
        return present(s, bundle)


@router.get("/index-bundles/{bundle_id}")
def bundle(bundle_id: str, request: Request):
    with request.state.store.session() as s:
        return present(s, scoped(s, IndexBundle, bundle_id))


@router.get("/jobs/{job_id}")
def job(job_id: str, request: Request):
    with request.state.store.session() as s:
        return present(s, scoped(s, Job, job_id))
