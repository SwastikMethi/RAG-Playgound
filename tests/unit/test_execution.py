import asyncio

import pytest

from rag_runtime.process import run_json
from rag_runtime.trace import Trace, empty_timing


@pytest.mark.asyncio
async def test_measured_failed_span_and_owned_subprocess_cancellation(tmp_path):
    now = [0.0]
    events, metrics = [], empty_timing()

    async def emit(kind, payload):
        events.append((kind, payload))

    with pytest.raises(ValueError):
        async with Trace(emit, metrics, clock=lambda: now[0]).span("retrieval"):
            now[0] = 0.123
            raise ValueError()
    assert metrics["retrieval_ms"] == 123
    assert events[-1][1]["duration_ms"] == 123
    output = tmp_path / "must-not-exist"
    task = asyncio.create_task(
        run_json(
            ["-c", f"import time,pathlib; time.sleep(1); pathlib.Path({str(output)!r}).touch()"],
            timeout=10,
            memory_mb=512,
            root=tmp_path,
        )
    )
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(1)
    assert not output.exists()
