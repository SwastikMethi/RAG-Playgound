import subprocess
import sys
from pathlib import Path


def test_private_environment_creation_never_overwrites_existing_keys(tmp_path):
    script = Path("tools/init_env.py").resolve()
    (tmp_path / ".env.example").write_text("RAG_MASTER_KEY=\nOPENAI_API_KEY=\n")
    subprocess.run([sys.executable, str(script)], cwd=tmp_path, check=True, capture_output=True)
    value = (tmp_path / ".env").read_bytes()
    assert len(value.splitlines()[0]) > 40
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    second = subprocess.run([sys.executable, str(script)], cwd=tmp_path, check=True, capture_output=True)
    assert (tmp_path / ".env").read_bytes() == value and value not in second.stdout


def test_local_app_lifecycle(tmp_path, monkeypatch):
    import json
    import socket
    import psutil
    import pytest
    from tools import local_app

    # Real detached processes and HTTP, without touching the owner's Docker data.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    (tmp_path / ".env").touch()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "server.py").write_text(
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        '  self.send_response(200); self.end_headers(); self.wfile.write(b\'{"status":"ok"}\')\n'
        f"HTTPServer(('127.0.0.1', {port}), Handler).serve_forever()\n"
    )
    commands = {
        "api": [sys.executable, str(tmp_path / "server.py")],
        "worker": [sys.executable, "-u", "-c", "import time; print('Worker ready'); time.sleep(300)"],
    }
    monkeypatch.setattr(local_app, "ROOT", tmp_path)
    monkeypatch.setattr(local_app, "STATE", tmp_path / ".data/run/processes.json")
    monkeypatch.setattr(local_app, "LOGS", tmp_path / ".data/logs")
    monkeypatch.setattr(local_app, "PORT", port)
    monkeypatch.setattr(local_app, "COMMANDS", commands)
    calls = []
    monkeypatch.setattr(local_app.subprocess, "run", lambda args, **kwargs: calls.append(args))
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        # Reused PIDs must never cause stop to signal an unrelated process.
        local_app.STATE.parent.mkdir(parents=True)
        local_app.STATE.write_text(json.dumps({"api": {"pid": unrelated.pid, "created": 0}}))
        local_app.stop()
        assert unrelated.poll() is None
        local_app.start()
        saved = local_app.STATE.read_bytes()
        processes = list(local_app.running().values())
        assert len(processes) == 2
        call_count = len(calls)
        local_app.start()
        assert local_app.STATE.read_bytes() == saved and len(calls) == call_count
        local_app.stop()
        local_app.stop()
        assert not local_app.STATE.exists()
        assert all(not p.is_running() or p.status() == psutil.STATUS_ZOMBIE for p in processes)
        assert unrelated.poll() is None
        assert all("down" not in args and "-v" not in args for args in calls)

        # A worker that fails during startup must not leave a half-running app.
        commands["worker"] = [sys.executable, "-c", "raise SystemExit(1)"]
        with pytest.raises(RuntimeError, match="worker exited"):
            local_app.start()
        assert not local_app.STATE.exists() and not local_app.running()
        assert not local_app.ready()
    finally:
        local_app.stop()
        unrelated.terminate()
        unrelated.wait(timeout=5)
