import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from uuid import uuid4

from .errors import Problem

Emit = Callable[[str, dict], Awaitable[None]]


def empty_timing():
    return {
        key: None
        for key in ("retrieval_ms", "context_ms", "generation_ms", "ttft_ms", "total_ms", "provider_wait_ms")
    }


@dataclass
class Span:
    id: str
    stage: str
    started: float
    details: dict = field(default_factory=dict)
    wait_ms: float = 0
    duration_ms: float = 0


class Trace:
    def __init__(self, emit: Emit, metrics=None, clock=time.monotonic):
        self.emit = emit
        self.metrics = metrics
        self.clock = clock

    @asynccontextmanager
    async def span(self, stage: str, parent=None, details=None, attempt=1):
        span = Span(uuid4().hex, stage, self.clock())
        await self.emit(
            "stage.started",
            dict(
                span_id=span.id,
                stage=stage,
                parent_span_id=parent,
                attempt=attempt,
                display_label=stage.replace("_", " ").capitalize(),
                details=details or {},
            ),
        )
        try:
            yield span
        except BaseException as exc:
            span.duration_ms = (self.clock() - span.started) * 1000
            error = (
                exc
                if isinstance(exc, Problem)
                else Problem(
                    "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "STAGE_FAILED",
                    "Operation cancelled."
                    if isinstance(exc, asyncio.CancelledError)
                    else "The operation could not finish.",
                )
            )
            await self.emit(
                "stage.failed",
                dict(
                    span_id=span.id,
                    stage=stage,
                    duration_ms=span.duration_ms,
                    error=error.public(),
                ),
            )
            raise
        else:
            span.duration_ms = (self.clock() - span.started) * 1000
            await self.emit(
                "stage.completed",
                dict(
                    span_id=span.id,
                    stage=stage,
                    duration_ms=span.duration_ms,
                    resource_wait_ms=span.wait_ms,
                    details=span.details,
                ),
            )
        finally:
            key = {
                "retrieval": "retrieval_ms",
                "context_packing": "context_ms",
                "generation": "generation_ms",
            }.get(stage)
            if key and self.metrics is not None:
                self.metrics[key] = span.duration_ms
