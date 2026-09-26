"""Metadata and durable execution; migrations exclusively own table creation."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return uuid4().hex


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Identity, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Identity, Base):
    __tablename__ = "artifacts"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    relative_storage_key: Mapped[str] = mapped_column(Text)
    byte_count: Mapped[int] = mapped_column(BigInteger)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ready")


class Source(Identity, Base):
    __tablename__ = "sources"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    display_name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="processing", index=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"))
    parsed_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"))
    job_id: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[dict | None] = mapped_column(JSON)


class Corpus(Identity, Base):
    __tablename__ = "corpus_versions"
    __table_args__ = (UniqueConstraint("project_id", "ordinal"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    content_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="ready")


class CorpusSource(Base):
    __tablename__ = "corpus_sources"
    corpus_version_id: Mapped[str] = mapped_column(ForeignKey("corpus_versions.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class Configuration(Identity, Base):
    __tablename__ = "pipeline_configs"
    __table_args__ = (UniqueConstraint("family_id", "revision"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    family_id: Mapped[str] = mapped_column(String(128), default=uid)
    name: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    based_on_config_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_configs.id"))
    config: Mapped[dict] = mapped_column(JSON)
    config_sha256: Mapped[str] = mapped_column(String(64))


class IndexBundle(Identity, Base):
    __tablename__ = "index_bundles"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    corpus_version_id: Mapped[str] = mapped_column(ForeignKey("corpus_versions.id"), index=True)
    config_id: Mapped[str] = mapped_column(ForeignKey("pipeline_configs.id"))
    requirements_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    job_id: Mapped[str | None] = mapped_column(String(128))
    artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    setup_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[dict | None] = mapped_column(JSON)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    corpus_version_id: Mapped[str] = mapped_column(ForeignKey("corpus_versions.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    variant_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(128))
    span: Mapped[dict] = mapped_column(JSON)
    text_sha256: Mapped[str] = mapped_column(String(64))
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))


class Run(Identity, Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_project_created", "project_id", "created_at"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    corpus_version_id: Mapped[str] = mapped_column(ForeignKey("corpus_versions.id"))
    question: Mapped[str] = mapped_column(Text)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    queue_ms: Mapped[float | None]
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Lane(Identity, Base):
    __tablename__ = "lanes"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    config_id: Mapped[str] = mapped_column(ForeignKey("pipeline_configs.id"))
    bundle_id: Mapped[str] = mapped_column(ForeignKey("index_bundles.id"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    config_snapshot: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    answer: Mapped[str] = mapped_column(Text, default="")
    answer_kind: Mapped[str | None] = mapped_column(String(30))
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[dict | None] = mapped_column(JSON)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), unique=True)
    lane_id: Mapped[str | None] = mapped_column(ForeignKey("lanes.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(40))
    emitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[float]
    payload: Mapped[dict] = mapped_column(JSON)


class Job(Identity, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    owner_token: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[dict | None] = mapped_column(JSON)


class Feedback(Base):
    __tablename__ = "feedback"
    lane_id: Mapped[str] = mapped_column(ForeignKey("lanes.id", ondelete="CASCADE"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    helpful: Mapped[str] = mapped_column(String(20), default="unset")
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Preference(Base):
    __tablename__ = "run_preferences"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    preferred_lane_id: Mapped[str | None] = mapped_column(ForeignKey("lanes.id", ondelete="SET NULL"))
    tied_lane_ids: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Connection(Identity, Base):
    __tablename__ = "connections"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    public_config: Mapped[dict] = mapped_column(JSON)
    encrypted_secret: Mapped[str] = mapped_column(Text)
    secret_key_version: Mapped[int] = mapped_column(Integer, default=1)


class Export(Identity, Base):
    __tablename__ = "exports"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    lane_id: Mapped[str] = mapped_column(ForeignKey("lanes.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    include_data: Mapped[bool] = mapped_column(default=False)
    verification_mode: Mapped[str] = mapped_column(String(20), default="offline")
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"))
    job_id: Mapped[str | None] = mapped_column(String(128))
    manifest: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(String(100), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_resource_id: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
