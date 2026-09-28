from pathlib import Path

import pytest

from rag_runtime.errors import Problem
from workers import export


@pytest.mark.parametrize(
    ("technique", "source_format", "required", "excluded"),
    [
        (
            "bm25",
            "text",
            {"parsing.py"},
            {"reranker.py", "pageindex_adapter.py", "pageindex_build.py", "postgres_source.py", "operational.py"},
        ),
        (
            "hybrid_rerank",
            "text",
            {"parsing.py", "reranker.py"},
            {"pageindex_adapter.py", "pageindex_build.py", "postgres_source.py", "operational.py"},
        ),
        (
            "pageindex",
            "pdf",
            {"parsing.py", "pageindex_adapter.py", "pageindex_build.py"},
            {"reranker.py", "postgres_source.py", "operational.py"},
        ),
        (
            "bm25",
            "postgres_snapshot",
            {"postgres_source.py"},
            {"parsing.py", "reranker.py", "pageindex_adapter.py", "pageindex_build.py", "operational.py"},
        ),
    ],
)
def test_package_contains_only_the_selected_runtime_adapters(
    tmp_path, technique, source_format, required, excluded
):
    config = {
        "technique": technique,
        "embedding": {} if technique in {"hybrid_rerank"} else None,
        "reranker": {} if technique == "hybrid_rerank" else None,
        "tree": {} if technique == "pageindex" else None,
    }
    files = export.write_package(
        tmp_path / technique,
        config,
        [],
        [{"source_format": source_format, "file_alias": "source.txt"}],
        {"include_data": False},
        [],
    )
    runtime = {Path(name).name for name in files if name.startswith("src/rag_runtime/")}
    assert required <= runtime
    assert not excluded & runtime


def test_package_rejects_runtime_symlinks_and_traversal(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "__init__.py").symlink_to(Path(export.runtime.__file__))
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
