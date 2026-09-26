"""PostgreSQL job worker. Provider calls only occur outside metadata transactions."""

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

import psutil
from sqlalchemy import select

from app.database import Store, scoped
from app.models import (
    Artifact,
    Chunk,
    Configuration,
    Corpus,
    CorpusSource,
    IndexBundle,
    Job,
    Lane,
    Run,
    Source,
)
from app.settings import Settings
from rag_runtime.chunking import chunk_source, parent_child_chunks
from rag_runtime.contracts import canonical, digest
from rag_runtime.errors import Problem
from rag_runtime.providers import Gateway, empty_usage, load_profiles
from rag_runtime.registry import check_config, preparation_identity
from rag_runtime.runtime import execute
from rag_runtime.trace import empty_timing
from .events import RunWriter


async def subprocess_json(arguments, settings, root):
    with tempfile.TemporaryDirectory(prefix="job-", dir=root) as temporary:
        output_path = Path(temporary) / "result.json"
        with output_path.open("wb") as output:
            env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path), HF_HUB_OFFLINE="1")
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                *arguments,
                stdout=output,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            started = time.monotonic()
            try:
                while process.returncode is None:
                    if time.monotonic() - started > settings.parser_timeout_seconds:
                        raise Problem(
                            "PARSER_TIMEOUT",
                            "Source parsing exceeded its time limit. Try a smaller document.",
                        )
                    try:
                        ps = psutil.Process(process.pid)
                        memory = ps.memory_info().rss + sum(
                            p.memory_info().rss for p in ps.children(recursive=True)
                        )
                    except psutil.NoSuchProcess:
                        memory = 0
                    if (
                        memory > settings.parser_memory_mb * 1024 * 1024
                        or output_path.stat().st_size > 16 * 1024 * 1024
                    ):
                        raise Problem("PARSER_LIMIT", "Source parsing exceeded its memory or output limit.")
                    try:
                        await asyncio.wait_for(process.wait(), 0.1)
                    except TimeoutError:
                        pass
            finally:
                if process.returncode is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
        try:
            data = json.loads(output_path.read_text())
        except (ValueError, OSError):
            raise Problem("PARSER_FAILED", "The parser could not process this source.") from None
        if "error" in data:
            error = data["error"]
            raise Problem(error["code"], error["message"])
        if process.returncode:
            raise Problem("PARSER_FAILED", "The parser exited without a complete result.")
        return data


class Worker:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.database_url, settings.artifact_root, settings.lease_seconds)
        self.profiles = load_profiles(settings)
        self.gateway = Gateway(settings.provider_concurrency, settings.embedding_concurrency)

    def close(self):
        self.store.engine.dispose()

    async def run_resource(self, resource_id):
        with self.store.session() as s:
            job = s.scalar(select(Job).where(Job.resource_id == resource_id, Job.status == "queued").limit(1))
            id = job.id if job else None
        return await self.run_once(id) if id else False

    async def watch(self, claim, task):
        while not task.done():
            await asyncio.sleep(self.settings.heartbeat_seconds)
            try:
                with self.store.session() as s:
                    job = self.store.owned(s, claim["id"], claim["owner_token"])
                    cancel = bool(job.cancel_requested_at)
                if cancel:
                    task.cancel()
                    return
                self.store.heartbeat(claim["id"], claim["owner_token"])
            except Problem:
                task.cancel()
                return

    async def run_once(self, job_id=None):
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
                    if error and error.code == "CANCELLED"
                    else ("failed" if error else "succeeded")
                )
                job.completed_at, job.error = self.store.now(s), error.public() if error else None
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
            artifact = scoped(s, Artifact, source.raw_artifact_id, source.project_id)
            path, kind, name = (
                self.store.path(artifact),
                source.source_metadata["format"],
                source.display_name,
            )
        parsed = await subprocess_json(
            ["-m", "rag_runtime.parsing", str(path), kind], self.settings, self.store.root
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
                variant_fingerprint=bundle.requirements_sha256,
            )
        chunks, parents = [], []
        for source in sources:
            if config["parent"]:
                children, expanded = parent_child_chunks(
                    source, config["chunking"], config["parent"]["max_parent_tokens"]
                )
                chunks.extend(children)
                parents.extend(expanded)
            else:
                chunks.extend(chunk_source(source, config["chunking"]))
        if not chunks or len(chunks) > 10_000:
            raise Problem("CHUNK_LIMIT", "Preparation requires 1–10,000 chunks.")
        prepared = dict(chunks=chunks, parents=parents, scope=scope, format_version="1", recordings=[])
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
        await asyncio.gather(*(self.lane(claim, writer, lane, question) for lane in lanes))
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

        async def emit(kind, payload):
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
                prepared = json.loads(self.store.read(s, bundle.artifact_ids[0], claim["project_id"]))
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
                    cache_state="cold",
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
            if result.get("answer"):
                result["usage"]["accounting"] = "partial"
            payload = dict(metrics=result["metrics"], usage=result["usage"])
            payload.update(
                reason="Cancelled by owner." if status == "cancelled" else None
            ) if status == "cancelled" else payload.update(error=error.public())
            try:
                await emit("lane." + status, payload)
            except Problem as failure:
                if failure.code != "WORKER_LOST":
                    raise


async def main():
    worker = Worker(Settings())
    print("Worker ready", flush=True)
    try:
        while True:
            if not await worker.run_once():
                await asyncio.sleep(0.25)
    finally:
        worker.close()


if __name__ == "__main__":
    asyncio.run(main())
