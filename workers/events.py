"""A fenced, transactional writer: materialized state and each event commit together."""

import asyncio
import time

from sqlalchemy import select

from app.database import scoped
from app.models import Lane, Run, RunEvent
from app.runs import TERMINAL
from rag_runtime.contracts import canonical, validate
from rag_runtime.errors import Problem


class RunWriter:
    def __init__(self, store, claim):
        self.store, self.claim = store, claim
        self.origin = time.monotonic()
        self.lock = asyncio.Lock()
        self.buffers, self.timers, self.first_delta = {}, {}, set()

    async def emit(self, lane_id, kind, payload):
        async with self.lock:
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
            self.flush(lane_id)
            self.write(lane_id, kind, payload)
            if kind == "answer.delta":
                self.first_delta.add(lane_id)

    async def flush_later(self, lane_id):
        await asyncio.sleep(0.05)
        async with self.lock:
            self.flush(lane_id)

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
            if run.status in TERMINAL:
                raise Problem("RUN_TERMINAL", "This run has already finished.", 409)
            lane = (
                s.scalar(select(Lane).where(Lane.id == lane_id, Lane.run_id == run.id).with_for_update())
                if lane_id
                else None
            )
            if lane_id and (not lane or lane.status in TERMINAL):
                raise Problem("LANE_TERMINAL", "This lane has already finished.", 409)
            now = self.store.now(s)
            event = dict(
                schema_version="1.0.0",
                event_id=f"{run.id}:{run.last_seq + 1}",
                run_id=run.id,
                lane_id=lane_id,
                seq=run.last_seq + 1,
                emitted_at=now.isoformat(),
                elapsed_ms=(time.monotonic() - self.origin) * 1000,
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
                    **{
                        key: value
                        for key, value in event.items()
                        if key not in {"schema_version", "emitted_at"}
                    },
                    emitted_at=now,
                )
            )
