"""Hosted admission limits run in the same transaction as the reserved resources."""
import shutil
from sqlalchemy import func, select
from rag_runtime.errors import Problem
from .models import Artifact, Corpus, Configuration, Export, IndexBundle, Job, Project, Run, Source


def exceeded(message):
    raise Problem("QUOTA_EXCEEDED", message, 429)


def disk_space(store, size=0):
    if store.artifacts:
        return
    if shutil.disk_usage(store.root).free - size < store.settings.min_free_bytes:
        raise Problem("STORAGE_FULL", "Storage is nearly full. Remove unused sources or try again later.", 503)


def owner_projects(s, owner):
    return select(Project.id).where(Project.owner_id == owner)


def artifact_admission(store, s, project_id, kind, size):
    disk_space(store, size)
    owner = s.scalar(select(Project.owner_id).where(Project.id == project_id))
    if owner is None:
        raise Problem("NOT_FOUND", "This project has no hosted owner.", 404)
    scope = Artifact.project_id.in_(owner_projects(s, owner))
    used = s.scalar(select(func.coalesce(func.sum(Artifact.byte_count), 0)).where(scope))
    if used + size > store.settings.max_artifact_bytes_per_user:
        exceeded("Your artifact storage limit is reached. Remove unused sources before adding more.")
    if kind in {"raw_source", "raw_snapshot"}:
        raw = s.scalar(select(func.coalesce(func.sum(Artifact.byte_count), 0)).where(scope, Artifact.kind.in_(["raw_source", "raw_snapshot"])))
        if raw + size > store.settings.max_upload_bytes_per_user:
            exceeded("Your upload storage limit is reached. Remove unused sources before uploading more.")


def admission(s, flush_context, instances):
    store = s.info["store"]
    new = list(s.new)
    projects = [p for p in new if isinstance(p, Project)]
    for owner in {p.owner_id for p in projects}:
        if owner is None:
            raise Problem("UNAUTHENTICATED", "A hosted project needs an owner.", 401)
        used = s.scalar(select(func.count()).select_from(Project).where(Project.owner_id == owner))
        if used + sum(p.owner_id == owner for p in projects) > store.settings.max_projects_per_user:
            exceeded("Your project limit is reached.")
    jobs = [j for j in new if isinstance(j, Job) and j.kind != "delete_source"]
    if jobs:
        queued = Job.status == "queued"
        total = s.scalar(select(func.count()).select_from(Job).where(queued, Job.kind != "delete_source"))
        if total + len(jobs) > store.settings.max_queued_jobs:
            exceeded("The job queue is full. Try again after existing work finishes.")
        owners = {s.scalar(select(Project.owner_id).where(Project.id == j.project_id)) for j in jobs}
        for owner in owners:
            if owner is None:
                raise Problem("NOT_FOUND", "This job has no hosted owner.", 404)
            ids = set(s.scalars(owner_projects(s, owner)))
            used = s.scalar(select(func.count()).select_from(Job).where(queued, Job.project_id.in_(ids), Job.kind != "delete_source"))
            if used + sum(j.project_id in ids for j in jobs) > store.settings.max_queued_per_user:
                exceeded("Your job queue is full. Wait for existing work or cancel queued jobs.")
    if any(isinstance(obj, (Project, Corpus, Configuration, Source, IndexBundle, Run, Export)) for obj in new) or jobs:
        disk_space(store)


def reserve_vectors(store, s, job, count):
    if not store.settings or store.settings.deployment != "hosted":
        return
    disk_space(store, count * job.progress["vector_dimensions"] * 4)
    owner = s.scalar(select(Project.owner_id).where(Project.id == job.project_id))
    rows = s.scalars(select(Job).where(Job.project_id.in_(owner_projects(s, owner)), Job.kind == "prepare_index", Job.id != job.id))
    used = sum(j.progress.get("reserved_vectors", 0) for j in rows if not j.progress.get("vector_cleanup_done"))
    if used + count > store.settings.max_vectors_per_user:
        exceeded("Your vector limit is reached. Remove unused sources before preparing more indexes.")
    job.progress = dict(job.progress, reserved_vectors=count)
