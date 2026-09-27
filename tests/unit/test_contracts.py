"""Catch broken relative schema resolution and incompatible example payloads."""

import json
import subprocess
import sys
from pathlib import Path
import pytest

from rag_runtime.contracts import request
from rag_runtime.errors import Problem


def test_pack_validates_external_schema_references():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "tools/validate_pack.py")], capture_output=True, text=True, cwd=root
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["standard_openapi_validation"] == "passed"
    assert report["schema_engine"] == "jsonschema_draft202012_plus_pack_semantics"


def test_oversized_source_selection_explains_the_limit_without_exposing_ids():
    with pytest.raises(Problem) as error:
        request({"source_ids": [f"private-source-{i}" for i in range(51)]}, "CreateCorpus")
    assert error.value.message == "Select at most 50 sources per corpus (51 selected)."
    assert error.value.details == {"field": "source_ids", "rule": "maxItems"}
    assert "private-source" not in str(error.value.public())
