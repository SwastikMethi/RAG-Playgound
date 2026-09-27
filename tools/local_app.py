"""Local start/stop implementation shared by the two shell entry points."""

import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import psutil

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".data/run/processes.json"
LOGS = ROOT / ".data/logs"
PORT = 8780
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.dev.yaml"]
COMMANDS = {
    "api": [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
        "--no-access-log",
    ],
    "worker": [sys.executable, "-m", "workers.main"],
}


def running():
    result = {}
    for name, saved in json.loads(STATE.read_text() if STATE.exists() else "{}").items():
        try:
            process = psutil.Process(saved["pid"])
            if (
                name in COMMANDS
                and process.create_time() == saved["created"]
                and process.cmdline() == COMMANDS[name]
                and process.cwd() == str(ROOT)
                and process.status() != psutil.STATUS_ZOMBIE
            ):
                result[name] = process
        except psutil.NoSuchProcess:
            pass
    return result


def stop_processes(processes=None):
    processes = list(running().values()) if processes is None else list(processes)
    for process in list(processes):
        try:
            processes.extend(process.children(recursive=True))
        except psutil.NoSuchProcess:
            pass
    for process in processes:
        try:
            process.send_signal(signal.SIGINT)
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=10)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=5)
    if alive:
        raise RuntimeError("Some app processes could not be stopped; retained the PID file for retry.")
    STATE.unlink(missing_ok=True)


def ready():
    try:
        with urlopen(f"http://127.0.0.1:{PORT}/api/v1/system/readiness", timeout=2) as response:
            return json.load(response).get("status") == "ok"
    except (OSError, URLError, ValueError):
        return False


def start():
    active = running()
    if len(active) == 2 and ready():
        print(f"Already running: http://127.0.0.1:{PORT}")
        return
    if active:
        raise RuntimeError("The app is only partially ready. Run ./stop.sh, then ./start.sh.")
    for path, instruction in [
        (".env", "uv run python tools/init_env.py, then configure .env"),
        ("node_modules", "npm ci"),
    ]:
        if not (ROOT / path).exists():
            raise RuntimeError(f"Missing {path}. Run {instruction} first.")
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", PORT))
        except OSError as error:
            raise RuntimeError(
                f"Port {PORT} is occupied. Stop its existing server before starting this app."
            ) from error
    subprocess.run(
        COMPOSE + ["up", "-d", "--wait", "--wait-timeout", "60", "postgres", "qdrant"], cwd=ROOT, check=True
    )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
    subprocess.run(["npm", "run", "build"], cwd=ROOT, check=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    saved, children = {}, {}
    try:
        for name, command in COMMANDS.items():
            with (LOGS / f"{name}.log").open("w") as log:
                child = psutil.Popen(
                    command,
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            children[name] = child
            saved[name] = {"pid": child.pid, "created": child.create_time()}
            temporary = STATE.with_suffix(".tmp")
            temporary.write_text(json.dumps(saved))
            temporary.replace(STATE)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            for name, child in children.items():
                if child.poll() is not None:
                    raise RuntimeError(f"{name} exited during startup. Check {LOGS / (name + '.log')}.")
            if ready() and "Worker ready" in (LOGS / "worker.log").read_text():
                print(f"RAG Playground: http://127.0.0.1:{PORT}\nLogs: {LOGS}\nStop: ./stop.sh")
                return
            time.sleep(0.5)
        raise RuntimeError(f"Startup timed out. Check logs in {LOGS}.")
    except BaseException:
        stop_processes(children.values())
        raise


def stop():
    stop_processes()
    subprocess.run(COMPOSE + ["stop", "postgres", "qdrant"], cwd=ROOT, check=True)
    print("RAG Playground stopped. Uploads, indexes and database volumes are preserved.")


if __name__ == "__main__":
    os.umask(0o077)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (STATE.parent / "lifecycle.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            {"start": start, "stop": stop}[sys.argv[1]]()
    except BlockingIOError:
        sys.exit("Another start/stop command is still running.")
    except (OSError, RuntimeError, ValueError, psutil.Error, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
