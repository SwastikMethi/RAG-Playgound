import os
from contextlib import contextmanager
from copy import copy
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from rag_runtime.contracts import digest
from rag_runtime.errors import Problem
from .models import Artifact, AuthSession, Job, Project, uid


def scoped(session, model, resource_id, project_id=None, lock=False):
    query = select(model).where(model.id == resource_id)
    if project_id is not None:
        query = query.where(model.project_id == project_id)
    owner = session.info.get("owner_id")
    if owner is not None:
        if model is Project:
            query = query.where(Project.owner_id == owner)
        else:
            query = query.where(model.project_id.in_(select(Project.id).where(Project.owner_id == owner)))
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise Problem("NOT_FOUND", "This resource is unavailable in the selected project.", 404)
    return row


class Store:
    def __init__(self, url, artifact_root=Path(".data/artifacts"), lease_seconds=30, settings=None):
        self.engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)
        self.root = Path(artifact_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lease_seconds = lease_seconds
        self.settings = settings
        self.owner_id = self.session_hash = None

    def for_user(self, owner_id, session_hash):
        scoped_store = copy(self)
        scoped_store.owner_id, scoped_store.session_hash = owner_id, session_hash
        return scoped_store

    @contextmanager
    def session(self):
        with Session(self.engine, expire_on_commit=False) as session:
            try:
                with session.begin():
                    session.info["store"] = self
                    if self.settings and self.settings.deployment == "hosted":
                        # ponytail: serialize short metadata transactions for atomic quotas across API/worker.
                        # Split admission locks by account if measured contention warrants it.
                        from .quotas import admission
                        session.execute(text("SELECT pg_advisory_xact_lock(71234005)"))
                        event.listen(session, "before_flush", admission)
                    if self.owner_id is not None:
                        auth = session.get(AuthSession, self.session_hash)
                        if not auth or auth.user_id != self.owner_id or auth.expires_at <= self.now(session):
                            raise Problem("UNAUTHENTICATED", "Sign in to continue.", 401)
                        session.info["owner_id"] = self.owner_id
                    yield session
            except BaseException:
                for path in session.info.get("created_paths", []):
                    path.unlink(missing_ok=True)
                raise

    @staticmethod
    def now(session):
        return session.scalar(select(func.clock_timestamp()))

    def claim(self, job_id=None, kinds=None, compare_limit=2):
        with self.session() as s:
            # ponytail: serialize short admission transactions; replace with per-kind locks only if measured contention warrants it.
            s.execute(text("SELECT pg_advisory_xact_lock(71234001)"))
            query = select(Job).where(Job.status == "queued")
            if job_id:
                query = query.where(Job.id == job_id)
            if kinds:
                query = query.where(Job.kind.in_(kinds))
            active = s.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.kind == "compare_run", Job.status == "running")
            )
            if active >= compare_limit:
                query = query.where(Job.kind != "compare_run")
            active_kinds = list(
                s.scalars(
                    select(Job.kind).where(Job.status == "running", Job.kind != "compare_run").distinct()
                )
            )
            if active_kinds:
                query = query.where(Job.kind.not_in(active_kinds))
            job = s.scalar(query.order_by(Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1))
            if not job:
                return None
            now = self.now(s)
            job.status, job.owner_token = "running", uid()
            job.started_at = job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            return {k: getattr(job, k) for k in ("id", "project_id", "resource_id", "kind", "owner_token")}

    def owned(self, session, job_id, token):
        job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if (
            not job
            or job.status != "running"
            or job.owner_token != token
            or job.lease_expires_at <= self.now(session)
        ):
            raise Problem("WORKER_LOST", "The worker no longer owns this lease.", 409)
        return job

    def heartbeat(self, job_id, token):
        with self.session() as s:
            job = self.owned(s, job_id, token)
            job.heartbeat_at = self.now(s)
            job.lease_expires_at = job.heartbeat_at + timedelta(seconds=self.lease_seconds)
            return True

    def path(self, artifact):
        raw = self.root / artifact.relative_storage_key
        path = raw.resolve()
        if (
            not path.is_relative_to(self.root)
            or raw.is_symlink()
            or any(p.is_symlink() for p in raw.parents if p.is_relative_to(self.root))
        ):
            raise Problem("INTERNAL_ERROR", "Invalid artifact location.", 500)
        return path

    def put(self, session, project_id, kind, content: bytes, manifest=None):
        if self.settings and self.settings.deployment == "hosted":
            from .quotas import artifact_admission
            artifact_admission(self, session, project_id, kind, len(content))
        artifact_id = uid()
        relative = f"{project_id}/{artifact_id}"
        target = self.root / relative
        if not target.resolve().is_relative_to(self.root):
            raise Problem("INTERNAL_ERROR", "Invalid artifact scope.", 500)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".partial")
        session.info.setdefault("created_paths", []).extend([temporary, target])
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            kind=kind,
            content_sha256=digest(content),
            relative_storage_key=relative,
            byte_count=len(content),
            manifest=manifest or {},
        )
        session.add(artifact)
        session.flush()
        return artifact

    def read(self, session, artifact_id, project_id):
        artifact = scoped(session, Artifact, artifact_id, project_id)
        content = self.path(artifact).read_bytes()
        if digest(content) != artifact.content_sha256:
            raise Problem("INTERNAL_ERROR", "Stored artifact failed its integrity check.", 500)
        return content
