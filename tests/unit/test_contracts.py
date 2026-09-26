"""Catch broken relative schema resolution and incompatible example payloads."""
import json
import subprocess
import sys
from pathlib import Path


def test_pack_validates_external_schema_references():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "tools/validate_pack.py")],
                            capture_output=True, text=True, cwd=root)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["standard_openapi_validation"] == "passed"
    assert report["schema_engine"] == "jsonschema_draft202012_plus_pack_semantics"
