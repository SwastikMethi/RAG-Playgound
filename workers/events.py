"""A fenced, transactional writer: materialized state and each event commit together."""

import asyncio
import time
from copy import deepcopy

from sqlalchemy import select

from app.database import scoped
from app.models import Lane, Run, RunEvent
from app.runs import TERMINAL
from rag_runtime.contracts import canonical, validate
from rag_runtime.errors import Problem
from rag_runtime.operational import log_event


def persist_event(s, store, run, lane_id, kind, payload, elapsed):
    if run.status in TERMINAL:
        raise Problem("RUN_TERMINAL", "This run has already finished.", 409)
    lane = (
        s.scalar(select(Lane).where(Lane.id == lane_id, Lane.run_id == run.id).with_for_update())
        if lane_id
        else None
    )
    if lane_id and (not lane or lane.status in TERMINAL):
        raise Problem("LANE_TERMINAL", "This lane has already finished.", 409)
    closing = {
        "stage.failed",
        "lane.failed",
        "lane.cancelled",
        "lane.timed_out",
        "run.failed",
        "run.partial",
        "run.cancelled",
    }
    if kind not in closing and (run.cancel_requested_at or (lane and lane.cancel_requested_at)):
        raise asyncio.CancelledError
    now = store.now(s)
    event = dict(
        schema_version="1.0.0",
        event_id=f"{run.id}:{run.last_seq + 1}",
        run_id=run.id,
        lane_id=lane_id,
        seq=run.last_seq + 1,
        emitted_at=now.isoformat(),
        elapsed_ms=elapsed,
        type=kind,
        payload=payload,
    )
    validate(event, "trace-event.schema.json")
    if len(canonical(event)) > 128 * 1024:
        raise Problem("TRACE_EVENT_LIMIT", "The trace event exceeded its size limit.")
    if kind == "run.started":
        run.status, run.started_at, run.queue_ms = "running", now, payload["queue_ms"]
    elif kind.startswith("run."):
        run.status, run.completed_at = payload["status"], now
    if lane:
        if kind == "lane.started":
            lane.status = "running"
        elif kind == "answer.delta":
            if len(lane.answer) != payload["offset_chars"]:
                raise Problem("TRACE_OFFSET", "The persisted answer has a noncontiguous offset.", 500)
            lane.answer += payload["text"]
        elif kind == "answer.completed":
            lane.answer_kind = payload["answer_kind"]
        elif kind == "context.selected":
            lane.evidence = payload["evidence"]
        elif kind == "warning":
            lane.warnings = [*lane.warnings, payload["message"]]
        elif kind.startswith("lane.") and kind != "lane.started":
            lane.status = kind.split(".")[1]
            lane.metrics, lane.usage = payload["metrics"], payload["usage"]
            lane.error = payload.get("error")
            if kind == "lane.completed":
                lane.answer_kind = payload["answer_kind"]
    run.last_seq += 1
    s.add(
        RunEvent(
            **{key: value for key, value in event.items() if key not in {"schema_version", "emitted_at"}},
            emitted_at=now,
        )
    )
    return len(canonical(event))


class RunWriter:
    def __init__(self, store, claim):
        self.store, self.claim = store, claim
        self.origin = time.monotonic()
        self.lock = asyncio.Lock()
        self.buffers, self.timers, self.first_delta = {}, {}, set()
        self.trace_bytes = 0
        self.detail_artifacts = {}
        self.failure = None

    async def emit(self, lane_id, kind, payload):
        async with self.lock:
            closing = kind in {
                "stage.failed",
                "lane.failed",
                "lane.cancelled",
                "lane.timed_out",
                "run.failed",
                "run.partial",
                "run.cancelled",
            }
            if self.failure and not (closing and self.failure.code == "TRACE_LIMIT"):
                raise self.failure
            if kind == "answer.delta" and lane_id in self.first_delta:
                buffer = self.buffers.get(lane_id)
                if buffer:
                    if buffer["offset_chars"] + len(buffer["text"]) != payload["offset_chars"]:
                        raise Problem("TRACE_OFFSET", "The answer stream has a noncontiguous offset.", 500)
                    buffer["text"] += payload["text"]
                else:
                    self.buffers[lane_id] = dict(payload)
                    self.timers[lane_id] = asyncio.create_task(self.flush_later(lane_id))
                if len(self.buffers[lane_id]["text"].encode()) >= 2048:
                    self.flush(lane_id)
                return
            try:
                self.flush(lane_id)
            except Problem as exc:
                if not (closing and exc.code == "TRACE_LIMIT"):
                    raise
            self.write(lane_id, kind, payload)
            if kind == "answer.delta":
                self.first_delta.add(lane_id)

    async def flush_later(self, lane_id):
        await asyncio.sleep(0.05)
        async with self.lock:
            try:
                self.flush(lane_id)
            except Problem as exc:
                self.failure = exc

    def flush(self, lane_id):
        payload = self.buffers.pop(lane_id, None)
        timer = self.timers.pop(lane_id, None)
        if timer and timer != asyncio.current_task():
            timer.cancel()
        if payload:
            self.write(lane_id, "answer.delta", payload)

    def write(self, lane_id, kind, payload):
        with self.store.session() as s:
            self.store.owned(s, self.claim["id"], self.claim["owner_token"])
            run = scoped(s, Run, self.claim["resource_id"], self.claim["project_id"], lock=True)
            elapsed = (time.monotonic() - self.origin) * 1000
            if kind == "retrieval.candidates" and (
                len(canonical(payload)) > 96 * 1024 or self.trace_bytes > 4 * 1024 * 1024
            ):
                artifact = self.store.put(
                    s,
                    run.project_id,
                    "step_details",
                    canonical(dict(type=kind, payload=payload)),
                    dict(run_id=run.id, lane_id=lane_id, span_id=payload["span_id"]),
                )
                self.detail_artifacts[payload["span_id"]] = artifact.id
                lane = s.scalar(select(Lane).where(Lane.id == lane_id, Lane.run_id == run.id))
                lane.provenance = dict(
                    lane.provenance, artifact_ids=[*lane.provenance["artifact_ids"], artifact.id]
                )
                payload = deepcopy(payload)
                for candidate in payload["candidates"]:
                    if len(candidate["excerpt"]) > 400:
                        candidate["excerpt"] = candidate["excerpt"][:400]
                        location = candidate["location"]
                        location["char_end"] = location["char_start"] + 400
                        location["line_end"] = location["line_start"] + candidate["excerpt"][:-1].count("\n")
                        candidate["span_truncated"] = True
                while len(canonical(payload)) > 96 * 1024:
                    payload["candidates"].pop()
                self.trace_bytes += persist_event(
                    s,
                    self.store,
                    run,
                    lane_id,
                    "warning",
                    dict(
                        code="TRACE_DETAIL_COMPACTED",
                        message="Candidate previews are shortened. Full recorded detail is available in the step inspector.",
                    ),
                    elapsed,
                )
            detail = self.detail_artifacts.get(payload.get("span_id"))
            if detail and kind == "stage.completed":
                payload = dict(payload, details=dict(payload.get("details", {}), artifact_id=detail))
            if detail and kind == "stage.failed":
                payload = deepcopy(payload)
                payload["error"]["details"]["artifact_id"] = detail
            essential = (
                kind.startswith("lane.") or kind.startswith("run.") or kind in {"stage.failed", "warning"}
            )
            if self.trace_bytes + len(canonical(payload)) > 20 * 1024 * 1024 - 64 * 1024 and not essential:
                raise Problem(
                    "TRACE_LIMIT",
                    "The run reached its trace limit. Saved answers and terminal state are retained.",
                )
            self.trace_bytes += persist_event(s, self.store, run, lane_id, kind, payload, elapsed)
        if kind in {
            "stage.completed",
            "stage.failed",
            "lane.completed",
            "lane.failed",
            "lane.cancelled",
            "lane.timed_out",
        }:
            log_event(
                kind,
                job_id=self.claim["id"],
                run_id=self.claim["resource_id"],
                lane_id=lane_id,
                stage=payload.get("stage"),
                duration_ms=payload.get("duration_ms"),
                error_code=payload.get("error", {}).get("code"),
            )
