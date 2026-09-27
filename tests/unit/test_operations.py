import subprocess
import sys
from pathlib import Path


def test_private_environment_creation_never_overwrites_existing_keys(tmp_path):
    script = Path("tools/init_env.py").resolve()
    (tmp_path / ".env.example").write_text("RAG_APP_TOKEN=\nRAG_MASTER_KEY=\nOPENAI_API_KEY=\n")
    subprocess.run([sys.executable, str(script)], cwd=tmp_path, check=True, capture_output=True)
    value = (tmp_path / ".env").read_bytes()
    assert len(value.splitlines()[0]) > 40
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    second = subprocess.run([sys.executable, str(script)], cwd=tmp_path, check=True, capture_output=True)
    assert (tmp_path / ".env").read_bytes() == value and value not in second.stdout
