from pathlib import Path

import pytest

from rag_runtime.errors import Problem
from workers import export


def test_package_rejects_runtime_symlinks_and_traversal(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "unsafe.py").symlink_to(Path(export.runtime.__file__))
    with monkeypatch.context() as patch:
        patch.setattr(export, "RUNTIME", runtime)
        with pytest.raises(Problem, match="symlinks"):
            export.write_package(tmp_path / "package", {}, [], [], {}, [])
    with pytest.raises(Problem, match="archive path"):
        export.write_package(
            tmp_path / "package", {"technique": "bm25", "embedding": None}, [],
            [{"file_alias": "../../outside.txt"}], {"include_data": True}, [b"private"],
        )
    assert not (tmp_path / "outside.txt").exists()
