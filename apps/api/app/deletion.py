"""Confirmed source cleanup; the durable plan survives partial external-store failures."""

from fastapi import APIRouter, Request
from sqlalchemy import delete, or_, select
from rag_runtime.errors import Problem
from rag_runtime.retrieval import lexical_index
from rag_runtime.vectors import Scope
from .database import scoped
from .models import (
    Artifact,
    Chunk,
    Corpus,
    CorpusSource,
    Export,
    IdempotencyKey,
    IndexBundle,
    Job,
    Lane,
    Project,
    Run,
    Source,
)

router = APIRouter(prefix="/api/v1")


def require_corpus_ready(s, corpus):
    unavailable = s.scalar(
        select(Source.id)
        .join(CorpusSource)
        .where(
            CorpusSource.corpus_version_id == corpus.id,
            Source.project_id == corpus.project_id,
            Source.status != "ready",
        )
        .limit(1)
    )
    if unavailable:
        raise Problem("SOURCE_NOT_READY", "This corpus contains a source being removed or unavailable.", 409)


def dependencies(s, source):
    project = source.project_id
    corpora = list(
        s.scalars(
            select(Corpus.id)
            .join(CorpusSource)
            .where(CorpusSource.source_id == source.id, Corpus.project_id == project)
        )
    )
    bundles = list(
        s.scalars(
            select(IndexBundle).where(
                IndexBundle.project_id == project, IndexBundle.corpus_version_id.in_(corpora)
            )
        )
    )
    runs = list(
        s.scalars(select(Run.id).where(Run.project_id == project, Run.corpus_version_id.in_(corpora)))
    )
    exports = list(s.scalars(select(Export).where(Export.project_id == project, Export.run_id.in_(runs))))
    ids = [source.id, *corpora, *runs, *[b.id for b in bundles], *[e.id for e in exports]]
    jobs = list(s.scalars(select(Job).where(Job.project_id == project, Job.resource_id.in_(ids))))
    artifacts = {
        a for a in [source.raw_artifact_id, source.parsed_artifact_id, *[e.artifact_id for e in exports]] if a
    }
    for bundle in bundles:
        artifacts.update(bundle.artifact_ids)
    for lane in s.scalars(select(Lane).where(Lane.run_id.in_(runs))):
        artifacts.update(lane.provenance.get("artifact_ids", []))
    artifacts.update(
        s.scalars(
            select(Artifact.id).where(
                Artifact.project_id == project,
                or_(
                    Artifact.manifest["run_id"].as_string().in_(runs),
                    Artifact.manifest["corpus_version_id"].as_string().in_(corpora),
                ),
            )
        )
    )
    scopes = {}
    for job in jobs:
        if job.progress.get("vector_scope"):
            value = dict(scope=job.progress["vector_scope"], dimensions=job.progress["vector_dimensions"])
            scopes[value["scope"]["variant_fingerprint"]] = value
    return dict(
        corpus_ids=corpora,
        bundle_ids=[b.id for b in bundles],
        run_ids=runs,
        export_ids=[e.id for e in exports],
        artifact_ids=sorted(artifacts),
        vector_scopes=list(scopes.values()),
        resource_ids=ids,
        active_job_ids=[j.id for j in jobs if j.status in {"queued", "running"}],
    )


@router.get("/sources/{source_id}/impact")
def impact(source_id: str, request: Request):
    with request.state.store.session() as s:
        source = scoped(s, Source, source_id)
        d = dependencies(s, source)
        return dict(
            source_id=source.id,
            corpus_count=len(d["corpus_ids"]),
            run_count=len(d["run_ids"]),
            bundle_count=len(d["bundle_ids"]),
            export_count=len(d["export_ids"]),
            active_job_ids=d["active_job_ids"],
        )


@router.delete("/sources/{source_id}", status_code=202)
def request_deletion(source_id: str, cascade: bool, confirmation_source_id: str, request: Request):
    if not cascade or confirmation_source_id != source_id:
        raise Problem("CONFIRMATION_REQUIRED", "Confirm this exact source and its dependent content.")
    store = request.state.store
    with store.session() as s:
        source = scoped(s, Source, source_id)
        scoped(s, Project, source.project_id, lock=True)
        previous = s.get(Job, source.job_id) if source.job_id else None
        if source.status == "deleted" or (
            previous and previous.kind == "delete_source" and previous.status in {"queued", "running"}
        ):
            return dict(job_id=source.job_id, resource_id=source.id)
        plan = dependencies(s, source)
        if plan["active_job_ids"]:
            raise Problem(
                "RESOURCE_BUSY",
                "Stop the active source, preparation, comparison or export jobs before deleting.",
                409,
                details=dict(job_ids=plan["active_job_ids"]),
            )
        if previous and previous.kind == "delete_source":
            prior = previous.progress.get("delete_plan", {})
            for key in ("corpus_ids", "bundle_ids", "run_ids", "export_ids", "artifact_ids", "resource_ids"):
                plan[key] = sorted(set(plan[key] + prior.get(key, [])))
            scopes = {
                v["scope"]["variant_fingerprint"]: v
                for v in plan["vector_scopes"] + prior.get("vector_scopes", [])
            }
            plan["vector_scopes"] = list(scopes.values())
        job = Job(
            project_id=source.project_id,
            kind="delete_source",
            resource_id=source.id,
            progress=dict(delete_plan=plan),
        )
        s.add(job)
        s.flush()
        source.status, source.error, source.job_id = "deleting", None, job.id
        return dict(job_id=job.id, resource_id=source.id)


async def cleanup(worker, claim):
    store = worker.store
    project = claim["project_id"]
    with store.session() as s:
        job = store.owned(s, claim["id"], claim["owner_token"])
        plan = job.progress["delete_plan"]
    for value in plan["vector_scopes"]:
        if value["scope"]["project_id"] != project:
            raise Problem("VECTOR_SCOPE", "The cleanup vector scope does not match this project.")
        with store.session() as s:
            store.owned(s, claim["id"], claim["owner_token"])
        await worker.vector_store().delete(Scope(**value["scope"]), value["dimensions"])
    with store.session() as s:
        store.owned(s, claim["id"], claim["owner_token"])
        scoped(s, Project, project, lock=True)
        source = scoped(s, Source, claim["resource_id"], project)
        # Foreign keys cascade lane answers, events, feedback, preferences and exports.
        s.execute(delete(Run).where(Run.project_id == project, Run.id.in_(plan["run_ids"])))
        s.execute(
            delete(Chunk).where(Chunk.project_id == project, Chunk.corpus_version_id.in_(plan["corpus_ids"]))
        )
        s.execute(
            delete(IndexBundle).where(
                IndexBundle.project_id == project, IndexBundle.id.in_(plan["bundle_ids"])
            )
        )
        s.execute(delete(Corpus).where(Corpus.project_id == project, Corpus.id.in_(plan["corpus_ids"])))
        s.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.project_id == project,
                IdempotencyKey.response_resource_id.in_(plan["resource_ids"]),
            )
        )
        s.execute(
            delete(Job).where(
                Job.project_id == project,
                Job.resource_id.in_(plan["resource_ids"]),
                Job.kind != "delete_source",
            )
        )
        source.raw_artifact_id = source.parsed_artifact_id = source.content_sha256 = None
        source.display_name, source.source_metadata, source.size_bytes = "Deleted source", {}, 0
        s.flush()
        # Shared artifacts are retained if any surviving source, bundle, chunk or lane references them.
        retained = set()
        for src in s.scalars(select(Source).where(Source.project_id == project)):
            retained.update([src.raw_artifact_id, src.parsed_artifact_id])
        for bundle in s.scalars(select(IndexBundle).where(IndexBundle.project_id == project)):
            retained.update(bundle.artifact_ids)
        for lane in s.scalars(select(Lane).join(Run).where(Run.project_id == project)):
            retained.update(lane.provenance.get("artifact_ids", []))
        retained.update(s.scalars(select(Chunk.artifact_id).where(Chunk.project_id == project)))
        remaining = [id for id in plan["artifact_ids"] if id not in retained]
        for artifact in s.scalars(
            select(Artifact).where(Artifact.project_id == project, Artifact.id.in_(remaining))
        ):
            artifact.status = "deleting"
    # Purge the single worker process's caches before removing durable bytes.
    for key in list(worker.cache):
        if key[0] == project:
            _, size = worker.cache.pop(key)
            worker.cache_bytes -= size
    lexical_index.cache_clear()
    for artifact_id in remaining:
        with store.session() as s:
            store.owned(s, claim["id"], claim["owner_token"])
            artifact = s.scalar(
                select(Artifact).where(Artifact.id == artifact_id, Artifact.project_id == project)
            )
            if artifact:
                store.remove(artifact)
                s.delete(artifact)
    with store.session() as s:
        store.owned(s, claim["id"], claim["owner_token"])
        source = scoped(s, Source, claim["resource_id"], project)
        source.status, source.error = "deleted", None
