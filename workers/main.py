"""PostgreSQL job worker. Provider calls only occur outside metadata transactions."""

import asyncio
import json
import time
from collections import OrderedDict
from importlib.metadata import version

from sqlalchemy import select

from app.database import Store, scoped
from app.models import (
    Artifact,
    Chunk,
    Configuration,
    Connection,
    Corpus,
    CorpusSource,
    Export,
    IndexBundle,
    Job,
    Lane,
    Run,
    RunEvent,
    Source,
)
from app.settings import Settings
from app.runs import TERMINAL
from rag_runtime.chunking import chunk_source, parent_child_chunks
from rag_runtime.contracts import canonical, digest
from rag_runtime.errors import Problem
from rag_runtime.providers import Gateway, empty_usage, load_profiles
from rag_runtime.registry import check_config, preparation_identity
from rag_runtime.runtime import execute
from rag_runtime.process import run_json
from rag_runtime.trace import empty_timing
from rag_runtime.vectors import Scope, VectorStore
from .events import RunWriter, persist_event


class Worker:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.database_url, settings.artifact_root, settings.lease_seconds)
        self.profiles = load_profiles(settings)
        self.gateway = Gateway(settings.provider_concurrency, settings.embedding_concurrency)
        self.vectors = None
        self.cache = OrderedDict()
        self.cache_bytes = 0

    def vector_store(self):
        if self.vectors is None:
            self.vectors = VectorStore(self.settings.qdrant_url, self.settings.qdrant_collection_prefix)
        return self.vectors

    def load_prepared(self, s, artifact_id, project_id):
        key = (project_id, artifact_id)
        if key in self.cache:
            value, size = self.cache.pop(key)
            self.cache[key] = (value, size)
            return value, "warm"
        raw = self.store.read(s, artifact_id, project_id)
        value = json.loads(raw)
        while self.cache and (self.cache_bytes + len(raw) > 64 * 1024 * 1024 or len(self.cache) >= 4):
            _, (_, size) = self.cache.popitem(last=False)
            self.cache_bytes -= size
        if len(raw) <= 64 * 1024 * 1024:
            self.cache[key] = (value, len(raw))
            self.cache_bytes += len(raw)
        return value, "cold"

    def close(self):
        if self.vectors:
            self.vectors.close()
        self.store.engine.dispose()

    async def run_resource(self, resource_id):
        with self.store.session() as s:
            job = s.scalar(select(Job).where(Job.resource_id == resource_id, Job.status == "queued").limit(1))
            id = job.id if job else None
        return await self.run_once(id) if id else False

    async def reconcile(self):
        with self.store.session() as s:
            jobs = list(
                s.scalars(
                    select(Job)
                    .where(Job.status == "running", Job.lease_expires_at <= self.store.now(s))
                    .with_for_update(skip_locked=True)
                    .limit(50)
                )
            )
            error = Problem(
                "WORKER_LOST",
                "The worker stopped reporting. This execution was not retried; start a new run.",
            ).public()
            for job in jobs:
                job.status, job.error, job.completed_at = "failed", error, self.store.now(s)
                if job.kind == "compare_run":
                    self.fail_run(s, job, error)
                else:
                    model = {
                        "ingest_source": Source,
                        "prepare_index": IndexBundle,
                        "export_lane": Export,
                    }.get(job.kind)
                    resource = (
                        s.scalar(
                            select(model).where(
                                model.id == job.resource_id, model.project_id == job.project_id
                            )
                        )
                        if model
                        else None
                    )
                    if resource:
                        resource.status, resource.error = "failed", error

    def fail_run(self, s, job, error):
        run = scoped(s, Run, job.resource_id, job.project_id, lock=True)
        if run.status in TERMINAL:
            return
        lanes = list(s.scalars(select(Lane).where(Lane.run_id == run.id)))
        events = list(s.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)))
        elapsed = events[-1].elapsed_ms if events else 0
        active = {}
        for event in events:
            if event.type == "stage.started":
                active[event.payload["span_id"]] = event
            elif event.type in {"stage.completed", "stage.failed"}:
                active.pop(event.payload["span_id"], None)
        for lane in lanes:
            if lane.status in TERMINAL:
                continue
            for span_id, event in active.items():
                if event.lane_id == lane.id:
                    persist_event(
                        s,
                        self.store,
                        run,
                        lane.id,
                        "stage.failed",
                        dict(span_id=span_id, stage=event.payload["stage"], duration_ms=None, error=error),
                        elapsed,
                    )
            metrics = dict(lane.metrics)
            for event in events:
                if event.lane_id == lane.id and event.type == "stage.completed":
                    key = {
                        "retrieval": "retrieval_ms",
                        "context_packing": "context_ms",
                        "generation": "generation_ms",
                    }.get(event.payload["stage"])
                    if key:
                        metrics[key] = event.payload["duration_ms"]
            usage = dict(lane.usage, accounting="partial")
            persist_event(
                s,
                self.store,
                run,
                lane.id,
                "lane.failed",
                dict(error=error, metrics=metrics, usage=usage),
                elapsed,
            )
        status = "partial" if any(lane.status == "completed" for lane in lanes) else "failed"
        persist_event(
            s,
            self.store,
            run,
            None,
            "run." + status,
            dict(status=status, lane_ids=[lane.id for lane in lanes]),
            elapsed,
        )

    async def watch_lane(self, claim, lane_id, task):
        while not task.done():
            await asyncio.sleep(0.1)
            try:
                with self.store.session() as s:
                    self.store.owned(s, claim["id"], claim["owner_token"])
                    run = scoped(s, Run, claim["resource_id"], claim["project_id"])
                    lane = s.scalar(select(Lane).where(Lane.id == lane_id, Lane.run_id == run.id))
                    cancelled = run.cancel_requested_at or lane.cancel_requested_at or lane.status in TERMINAL
                if cancelled:
                    task.cancel()
                    return
            except Problem:
                task.cancel()
                return

    async def watch(self, claim, task):
        while not task.done():
            await asyncio.sleep(self.settings.heartbeat_seconds)
            try:
                with self.store.session() as s:
                    job = self.store.owned(s, claim["id"], claim["owner_token"])
                    cancel = bool(job.cancel_requested_at)
                if cancel and claim["kind"] != "compare_run":
                    task.cancel()
                    return
                self.store.heartbeat(claim["id"], claim["owner_token"])
            except Problem:
                task.cancel()
                return

    async def run_once(self, job_id=None):
        await self.reconcile()
        claim = self.store.claim(job_id, compare_limit=self.settings.max_compare_runs)
        if not claim:
            return False
        handler = {
            "ingest_source": self.ingest,
            "prepare_index": self.prepare,
            "compare_run": self.compare,
        }.get(claim["kind"])
        if handler is None:
            raise Problem("UNKNOWN_JOB", "This worker does not support the job type.")
        task = asyncio.create_task(handler(claim))
        watcher = asyncio.create_task(self.watch(claim, task))
        error = None
        try:
            await task
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            error = (
                exc
                if isinstance(exc, Problem)
                else Problem(
                    "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "JOB_FAILED",
                    "The job was cancelled."
                    if isinstance(exc, asyncio.CancelledError)
                    else "The job failed. Check service readiness and dependency installation.",
                )
            )
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        try:
            with self.store.session() as s:
                job = self.store.owned(s, claim["id"], claim["owner_token"])
                job.status = (
                    "cancelled"
                    if (error and error.code == "CANCELLED") or (not error and job.cancel_requested_at)
                    else ("failed" if error else "succeeded")
                )
                job.completed_at, job.error = self.store.now(s), error.public() if error else None
                if error and claim["kind"] == "compare_run":
                    self.fail_run(s, job, error.public())
                if error and claim["kind"] in {"ingest_source", "prepare_index"}:
                    model = Source if claim["kind"] == "ingest_source" else IndexBundle
                    resource = scoped(s, model, claim["resource_id"], claim["project_id"])
                    resource.status, resource.error = "failed", error.public()
        except Problem as exc:
            if exc.code != "WORKER_LOST":
                raise
        return True

    async def ingest(self, claim):
        with self.store.session() as s:
            self.store.owned(s, claim["id"], claim["owner_token"])
            source = scoped(s, Source, claim["resource_id"], claim["project_id"])
            postgres = source.kind == "postgres"
        if postgres:
            await self.capture_postgres(claim)
            return
        with self.store.session() as s:
            self.store.owned(s, claim["id"], claim["owner_token"])
            source = scoped(s, Source, claim["resource_id"], claim["project_id"])
            artifact = scoped(s, Artifact, source.raw_artifact_id, source.project_id)
            path, kind, name = (
                self.store.path(artifact),
                source.source_metadata["format"],
                source.display_name,
            )
        parsed = await run_json(
            ["-m", "rag_runtime.parsing", str(path), kind],
            timeout=self.settings.parser_timeout_seconds,
            memory_mb=self.settings.parser_memory_mb,
            root=self.store.root,
        )
        parsed.update(source_id=claim["resource_id"], name=name)
        with self.store.session() as s:
            self.store.owned(s, claim["id"], claim["owner_token"])
            source = scoped(s, Source, claim["resource_id"], claim["project_id"])
            artifact = self.store.put(s, source.project_id, "parsed_source", canonical(parsed))
            source.parsed_artifact_id, source.status = artifact.id, "ready"
            source.source_metadata = dict(
                source.source_metadata,
                parser=parsed["parser"],
                parser_revision=parsed["parser_revision"],
                characters=len(parsed["text"]),
                pages=len(parsed["segments"]) if kind == "pdf" else 0,
            )

    async def capture_postgres(self, claim):
        from app.connections import password
        from rag_runtime.postgres_source import capture

        with self.store.session() as s:
            self.store.owned(s, claim["id"], claim["owner_token"])
            source = scoped(s, Source, claim["resource_id"], claim["project_id"])
            connection = scoped(s, Connection, source.source_metadata["connection_id"], claim["project_id"])
            config, secret = connection.public_config, password(self.settings, connection)
            selection = source.source_metadata["selection"]
        try:
            snapshot = await capture(
                config,
                secret,
                self.settings.database_host_allowlist,
                self.settings.database_relation_allowlist,
                selection,
            )
        except TimeoutError:
            raise Problem("DATABASE_TIMEOUT", "Snapshot capture exceeded its time limit.") from None
        with self.store.session() as s:
            self.store.owned(s, claim["id"], claim["owner_token"])
            source = scoped(s, Source, claim["resource_id"], claim["project_id"])
            raw = self.store.put(s, source.project_id, "raw_snapshot", canonical(snapshot["raw"]))
            parsed = dict(snapshot["parsed"], source_id=source.id, name=source.display_name)
            artifact = self.store.put(s, source.project_id, "parsed_source", canonical(parsed))
            source.raw_artifact_id, source.parsed_artifact_id = raw.id, artifact.id
            source.size_bytes, source.content_sha256, source.status = (
                raw.byte_count,
                raw.content_sha256,
                "ready",
            )
            source.source_metadata = dict(
                source.source_metadata,
                characters=len(parsed["text"]),
                parser=parsed["parser"],
                parser_revision=parsed["parser_revision"],
                record_count=len(snapshot["raw"]["rows"]),
                **{
                    key: snapshot["raw"][key]
                    for key in ("relation", "captured_at", "skipped_empty_records", "truncated", "ordering")
                },
            )

    async def prepare(self, claim):
        began = time.monotonic()
        with self.store.session() as s:
            self.store.owned(s, claim["id"], claim["owner_token"])
            bundle = scoped(s, IndexBundle, claim["resource_id"], claim["project_id"])
            config = scoped(s, Configuration, bundle.config_id, bundle.project_id).config
            corpus = scoped(s, Corpus, bundle.corpus_version_id, bundle.project_id)
            check_config(config, self.profiles)
            if bundle.requirements_sha256 != preparation_identity(
                config, corpus.content_fingerprint, self.profiles
            ):
                raise Problem(
                    "PROFILE_CHANGED", "The provider profile changed after preparation was requested."
                )
            prior = s.scalar(
                select(IndexBundle)
                .where(
                    IndexBundle.project_id == bundle.project_id,
                    IndexBundle.corpus_version_id == corpus.id,
                    IndexBundle.requirements_sha256 == bundle.requirements_sha256,
                    IndexBundle.status == "ready",
                    IndexBundle.id != bundle.id,
                )
                .limit(1)
            )
            if prior:
                bundle.status, bundle.artifact_ids = "ready", prior.artifact_ids
                bundle.setup_metrics = dict(prior.setup_metrics, preparation_reused=True)
                return
            sources = [
                json.loads(self.store.read(s, src.parsed_artifact_id, bundle.project_id))
                for src in s.scalars(
                    select(Source)
                    .join(CorpusSource)
                    .where(
                        CorpusSource.corpus_version_id == corpus.id, Source.project_id == bundle.project_id
                    )
                    .order_by(CorpusSource.ordinal)
                )
            ]
            bundle.status = "preparing"
            scope = dict(
                project_id=bundle.project_id,
                corpus_version_id=corpus.id,
                variant_fingerprint=digest(
                    dict(requirements=bundle.requirements_sha256, build=claim["owner_token"])
                ),
            )
            if config["embedding"]:
                job = s.get(Job, claim["id"])
                job.progress = dict(vector_scope=scope, vector_dimensions=config["embedding"]["dimensions"])
        chunks, parents = [], []
        for source in sources:
            if config["tree"]:
                continue
            if config["parent"]:
                children, expanded = parent_child_chunks(
                    source, config["chunking"], config["parent"]["max_parent_tokens"]
                )
                chunks.extend(children)
                parents.extend(expanded)
            else:
                chunks.extend(chunk_source(source, config["chunking"]))
        if (not chunks and not config["tree"]) or len(chunks) > 10_000:
            raise Problem("CHUNK_LIMIT", "Preparation requires 1–10,000 chunks.")
        prepared = dict(
            chunks=chunks,
            parents=parents,
            scope=scope,
            format_version="1",
            recordings=[],
            versions=dict(bm25=version("rank-bm25"), lexical="lexical_v1", tokenizer=version("tiktoken")),
        )
        if config["tree"]:
            from rag_runtime.pageindex_build import build_document

            documents = []
            for source in sources:
                with self.store.session() as s:
                    self.store.owned(s, claim["id"], claim["owner_token"])
                    src = scoped(s, Source, source["source_id"], claim["project_id"])
                    raw = scoped(s, Artifact, src.raw_artifact_id, claim["project_id"])
                    path = self.store.path(raw)
                document = await build_document(
                    path,
                    source,
                    self.profiles[config["tree"]["index_profile_id"]],
                    self.gateway,
                    root=self.store.root,
                )
                prepared["recordings"].extend(document.pop("recordings"))
                documents.append(document)
            prepared["documents"] = documents
            prepared["versions"]["pageindex"] = config["tree"]["sdk_version"]
            prepared["preprocessing"] = (
                "PageIndex SDK builds the tree from the original PDF; final evidence uses canonical original-page extraction."
            )
        if config["embedding"]:
            emb = config["embedding"]
            vector = await self.gateway.embed(
                self.profiles[emb["profile_id"]],
                [emb["document_prefix"] + chunk["excerpt"] for chunk in chunks],
            )
            prepared["recordings"].append(vector["recording"])
            prepared["vectors"] = vector["vectors"]
            prepared["preparation_usage"] = vector["usage"]
            with self.store.session() as s:
                self.store.owned(s, claim["id"], claim["owner_token"])
            await self.vector_store().put(Scope(**scope), chunks, vector["vectors"], emb["dimensions"])
        with self.store.session() as s:
            self.store.owned(s, claim["id"], claim["owner_token"])
            bundle = scoped(s, IndexBundle, claim["resource_id"], claim["project_id"])
            artifact = self.store.put(s, bundle.project_id, "prepared_index", canonical(prepared), scope)
            for item in chunks + parents:
                id = digest(dict(**scope, candidate_id=item["candidate_id"]))
                if s.get(Chunk, id) is None:
                    s.add(
                        Chunk(
                            id=id,
                            **scope,
                            source_id=item["source_id"],
                            parent_id=item.get("parent_id"),
                            span=item["location"],
                            text_sha256=digest(item["excerpt"].encode()),
                            artifact_id=artifact.id,
                        )
                    )
            bundle.artifact_ids, bundle.status = [artifact.id], "ready"
            bundle.setup_metrics = dict(
                preparation_ms=(time.monotonic() - began) * 1000, preparation_reused=False
            )

    async def compare(self, claim):
        writer = RunWriter(self.store, claim)
        with self.store.session() as s:
            job = self.store.owned(s, claim["id"], claim["owner_token"])
            run = scoped(s, Run, claim["resource_id"], claim["project_id"])
            lanes = list(
                s.scalars(select(Lane).where(Lane.run_id == run.id).order_by(Lane.created_at, Lane.id))
            )
            queue_ms = max(0, (job.started_at - run.created_at).total_seconds() * 1000)
            question = run.question
        await writer.emit(None, "run.started", dict(lane_ids=[lane.id for lane in lanes], queue_ms=queue_ms))
        tasks = [asyncio.create_task(self.lane(claim, writer, lane, question)) for lane in lanes]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        with self.store.session() as s:
            states = list(s.scalars(select(Lane.status).where(Lane.run_id == claim["resource_id"])))
        status = (
            "completed"
            if all(v == "completed" for v in states)
            else (
                "cancelled"
                if all(v == "cancelled" for v in states)
                else "partial"
                if any(v == "completed" for v in states)
                else "failed"
            )
        )
        await writer.emit(None, "run." + status, dict(status=status, lane_ids=[lane.id for lane in lanes]))

    async def lane(self, claim, writer, lane, question):
        started = time.monotonic()
        result = dict(answer="", metrics=empty_timing(), usage=empty_usage(), recordings=[])
        with self.store.session() as s:
            current = s.scalar(select(Lane).where(Lane.id == lane.id, Lane.run_id == claim["resource_id"]))
            if current.status in TERMINAL:
                return
        watcher = asyncio.create_task(self.watch_lane(claim, lane.id, asyncio.current_task()))

        async def emit(kind, payload):
            if kind not in {"stage.failed", "lane.failed", "lane.cancelled", "lane.timed_out"}:
                with self.store.session() as s:
                    run = scoped(s, Run, claim["resource_id"], claim["project_id"])
                    current = s.scalar(select(Lane).where(Lane.id == lane.id, Lane.run_id == run.id))
                    if run.cancel_requested_at or current.cancel_requested_at:
                        raise asyncio.CancelledError()
            await writer.emit(lane.id, kind, payload)

        try:
            await emit(
                "lane.started",
                dict(
                    technique=lane.config_snapshot["technique"],
                    config_id=lane.config_id,
                    bundle_id=lane.bundle_id,
                ),
            )
            with self.store.session() as s:
                bundle = scoped(s, IndexBundle, lane.bundle_id, claim["project_id"])
                prepared, cache_state = self.load_prepared(s, bundle.artifact_ids[0], claim["project_id"])
            async with asyncio.timeout(lane.config_snapshot["limits"]["lane_timeout_ms"] / 1000):
                await execute(
                    question,
                    lane.config_snapshot,
                    prepared,
                    self.profiles,
                    self.gateway,
                    emit,
                    result,
                    started=started,
                    vector_store=self.vector_store() if lane.config_snapshot["embedding"] else None,
                )
            with self.store.session() as s:
                self.store.owned(s, claim["id"], claim["owner_token"])
                saved = s.scalar(select(Lane).where(Lane.id == lane.id, Lane.run_id == claim["resource_id"]))
                artifact = self.store.put(
                    s,
                    claim["project_id"],
                    "boundary_recordings",
                    canonical(result["recordings"]),
                    dict(lane_id=lane.id, run_id=claim["resource_id"]),
                )
                saved.provenance = dict(
                    saved.provenance,
                    artifact_ids=[*saved.provenance["artifact_ids"], artifact.id],
                    cache_state=cache_state,
                )
            result["metrics"]["total_ms"] = (time.monotonic() - started) * 1000
            await emit(
                "lane.completed",
                dict(answer_kind=result["answer_kind"], metrics=result["metrics"], usage=result["usage"]),
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            status = (
                "timed_out"
                if isinstance(exc, TimeoutError)
                else ("cancelled" if isinstance(exc, asyncio.CancelledError) else "failed")
            )
            error = (
                exc
                if isinstance(exc, Problem)
                else Problem(
                    "LANE_TIMEOUT"
                    if status == "timed_out"
                    else "CANCELLED"
                    if status == "cancelled"
                    else "LANE_FAILED",
                    "The lane exceeded its time limit."
                    if status == "timed_out"
                    else "The lane was cancelled."
                    if status == "cancelled"
                    else "The lane could not complete. Check its setup and providers.",
                )
            )
            result["metrics"]["total_ms"] = (time.monotonic() - started) * 1000
            if result.get("answer") or result.get("provider_attempted"):
                result["usage"]["accounting"] = "partial"
            payload = dict(metrics=result["metrics"], usage=result["usage"])
            payload.update(
                reason="Cancelled by owner." if status == "cancelled" else None
            ) if status == "cancelled" else payload.update(error=error.public())
            try:
                await emit("lane." + status, payload)
            except Problem as failure:
                if failure.code not in {"WORKER_LOST", "LANE_TERMINAL", "RUN_TERMINAL"}:
                    raise
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


async def main():
    worker = Worker(Settings())
    print("Worker ready", flush=True)

    async def slot():
        while True:
            if not await worker.run_once():
                await asyncio.sleep(0.25)

    try:
        await asyncio.gather(*(slot() for _ in range(5)))
    finally:
        worker.close()


if __name__ == "__main__":
    asyncio.run(main())
