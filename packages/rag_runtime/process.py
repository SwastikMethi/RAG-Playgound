"""Owned, bounded subprocesses shared by ingestion, reranking and export."""

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
import psutil
from .contracts import canonical
from .errors import Problem


async def run_json(arguments, timeout=120, memory_mb=2048, root=None, input_data=None, env_extra=None):
    with tempfile.TemporaryDirectory(prefix="job-", dir=root) as temporary:
        if input_data is not None:
            request_path = Path(temporary) / "request.json"
            request_path.write_bytes(canonical(input_data))
            arguments = [*arguments, str(request_path)]
        output_path = Path(temporary) / "result.json"
        with output_path.open("wb") as output:
            env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path), HF_HUB_OFFLINE="1")
            env.update(env_extra or {})
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
                    if time.monotonic() - started > timeout:
                        raise Problem(
                            "PROCESS_TIMEOUT",
                            "The isolated operation exceeded its time limit.",
                        )
                    try:
                        ps = psutil.Process(process.pid)
                        memory = ps.memory_info().rss + sum(
                            p.memory_info().rss for p in ps.children(recursive=True)
                        )
                    except psutil.NoSuchProcess:
                        memory = 0
                    if memory > memory_mb * 1024 * 1024 or output_path.stat().st_size > 16 * 1024 * 1024:
                        raise Problem(
                            "PROCESS_LIMIT", "The isolated operation exceeded its memory or output limit."
                        )
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
            raise Problem(
                "PROCESS_FAILED", "The isolated operation failed. Check its installed dependencies."
            ) from None
        if "error" in data:
            error = data["error"]
            raise Problem(error["code"], error["message"])
        if process.returncode:
            raise Problem("PROCESS_FAILED", "The isolated operation exited without a complete result.")
        return data
