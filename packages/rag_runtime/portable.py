"""Standalone application commands. The generated wrappers only select these operations."""

import argparse
import asyncio
import hmac
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from .contracts import canonical, digest, validate
from .errors import Problem
from .providers import Gateway, Profile
from .preparation import prepare_sources
from .process import run_json
from .registry import check_config
from .runtime import execute
from .vectors import Scope, VectorStore


def configuration(root):
    from dotenv import load_dotenv
    from .providers import load_profiles
    import yaml

    load_dotenv(root / ".env", override=False)
    config = validate(json.loads((root / "pipeline.json").read_text()))
    raw = yaml.safe_load((root / "profiles.yaml").read_text())["profiles"]
    fixture = any(p["kind"] == "fixture" for p in raw)
    if fixture:
        if not all(p["kind"] == "fixture" for p in raw):
            raise Problem(
                "PROFILE_INVALID", "Fixture and live profiles must not be mixed in this demonstration."
            )
        profiles = {p["id"]: Profile.model_validate(p) for p in raw}
    else:
        profiles = load_profiles(
            SimpleNamespace(
                mode="live",
                profiles_path=root / "profiles.yaml",
                provider_host_allowlist=json.loads(os.environ.get("RAG_PROVIDER_HOST_ALLOWLIST", "[]")),
            )
        )
    check_config(config, profiles)
    return config, profiles


def source_paths(root, folder):
    manifest = json.loads((root / "source-manifest.json").read_text())
    paths = []
    folder = Path(folder).resolve()
    for item in manifest:
        alias = item["file_alias"]
        if Path(alias).name != alias or "/" in alias or "\\" in alias:
            raise Problem("INVALID_MANIFEST", "Source aliases must be plain file names.")
        path = folder / alias
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(folder):
            raise Problem("SOURCE_REQUIRED", "Supply every file under its source-manifest alias.")
        if path.stat().st_size > 21 * 1024 * 1024 or digest(path.read_bytes()) != item["sha256"]:
            raise Problem(
                "SOURCE_HASH_MISMATCH",
                "A source differs from the exported snapshot. Restore its exact bytes; a new experiment needs a new manifest and index.",
            )
        paths.append((item, path))
    return paths


async def ingest(root, folder):
    config, profiles = configuration(root)
    paths = source_paths(root, folder)
    sources, raw_paths = [], {}
    for item, path in paths:
        if item["source_format"] == "postgres_snapshot":
            from .postgres_source import parse_snapshot

            parsed = parse_snapshot(path.read_bytes())
        else:
            parsed = await run_json(
                ["-m", "rag_runtime.parsing", str(path), item["source_format"]], timeout=120
            )
        sources.append(dict(parsed, source_id=item["source_id"], name=item["file_alias"]))
        raw_paths[item["source_id"]] = path
    if sum(len(s["text"]) for s in sources) > 2_000_000:
        raise Problem("CORPUS_LIMIT", "A corpus must contain at most two million characters.")
    scope = dict(
        project_id="portable",
        corpus_version_id=digest(json.loads((root / "source-manifest.json").read_text())),
        variant_fingerprint=uuid4().hex,
    )
    prepared = await prepare_sources(sources, config, scope, profiles, Gateway(), raw_paths=raw_paths)
    vector = None
    try:
        if config["embedding"]:
            vector = VectorStore(os.environ.get("RAG_QDRANT_URL", "http://127.0.0.1:6333"), "portable_rag")
            await vector.put(
                Scope(**scope), prepared["chunks"], prepared["vectors"], config["embedding"]["dimensions"]
            )
        state = root / ".rag"
        state.mkdir(mode=0o700, exist_ok=True)
        target = state / "index.json"
        temporary = state / ("index-" + uuid4().hex + ".tmp")
        temporary.touch(mode=0o600)
        temporary.write_bytes(canonical(dict(config_sha256=digest(config), prepared=prepared)))
        temporary.replace(target)
    finally:
        if vector:
            vector.close()
    return dict(
        status="ready",
        source_count=len(sources),
        chunk_count=len(prepared["chunks"]),
        fixture=any(p.kind == "fixture" for p in profiles.values()),
    )


async def query(root, question):
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 8000:
        raise Problem("VALIDATION_ERROR", "Provide a question of 1–8,000 characters.")
    config, profiles = configuration(root)
    path = root / ".rag/index.json"
    if not path.is_file():
        raise Problem("INDEX_MISSING", "Run scripts/ingest.py before querying.")
    state = json.loads(path.read_text())
    if state["config_sha256"] != digest(config):
        raise Problem("INDEX_MISMATCH", "Pipeline settings changed. Rebuild the index.")
    vector = (
        VectorStore(os.environ.get("RAG_QDRANT_URL", "http://127.0.0.1:6333"), "portable_rag")
        if config["embedding"]
        else None
    )
    try:

        async def emit(kind, payload):
            pass

        async with asyncio.timeout(config["limits"]["lane_timeout_ms"] / 1000):
            result = await execute(
                question, config, state["prepared"], profiles, Gateway(), emit, vector_store=vector
            )
        return {
            **{k: result[k] for k in ("answer", "answer_kind", "evidence", "metrics", "usage", "warnings")},
            "fixture": any(p.kind == "fixture" for p in profiles.values()),
        }
    finally:
        if vector:
            vector.close()


def static_check(root):
    import ast

    manifest = validate(json.loads((root / "manifest.json").read_text()), "export-manifest.schema.json")
    config = validate(json.loads((root / "pipeline.json").read_text()))
    if (
        digest(config) != manifest["pipeline_sha256"]
        or digest((root / "uv.lock").read_bytes()) != manifest["dependency_lock_sha256"]
    ):
        raise Problem("PACKAGE_CHANGED", "The pipeline or dependency lock differs from the manifest.")
    for path in root.rglob("*.py"):
        if ".venv" not in path.parts and ".rag" not in path.parts:
            if path.is_symlink():
                raise Problem("UNSAFE_PACKAGE", "Package sources cannot be symlinks.")
            ast.parse(path.read_text())
    return dict(
        status="passed",
        checks=["manifest", "pipeline", "dependency_lock", "python_syntax"],
        offline_replay=manifest["verification"]["offline_replay"],
        live_replay=manifest["verification"]["live_replay"],
    )


def main(operation, root):
    root = Path(root).resolve()
    parser = argparse.ArgumentParser()
    if operation == "ingest":
        parser.add_argument("--source-dir", default="data")
    elif operation == "query":
        parser.add_argument("question")
    else:
        parser.add_argument("private_request", nargs="?")
    args = parser.parse_args()
    try:
        if operation == "ingest":
            result = asyncio.run(ingest(root, args.source_dir))
        elif operation == "query":
            result = asyncio.run(query(root, args.question))
        elif args.private_request:
            from .export_replay import verify_replay
            import rag_runtime.runtime as runtime

            if not Path(runtime.__file__).resolve().is_relative_to(root / "src"):
                raise Problem("RUNTIME_MISMATCH", "Replay must import the exported runtime.")
            static_check(root)
            result = asyncio.run(verify_replay(json.loads(Path(args.private_request).read_text())))
        else:
            result = static_check(root)
        print(json.dumps(result, ensure_ascii=False))
    except (Problem, TimeoutError) as exc:
        error = (
            exc
            if isinstance(exc, Problem)
            else Problem("LANE_TIMEOUT", "The operation exceeded its deadline.")
        )
        print(json.dumps(dict(error=error.public())))
        raise SystemExit(1)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=8000)


def create_app(root):
    app = FastAPI(title="Exported RAG application", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(Problem)
    async def problem(request, error):
        return JSONResponse(dict(error=error.public()), status_code=error.status)

    @app.exception_handler(Exception)
    async def failed(request, error):
        return JSONResponse(
            dict(
                error=Problem(
                    "QUERY_FAILED", "Check the local index, model profiles and service readiness."
                ).public()
            ),
            status_code=500,
        )

    @app.get("/health")
    def health():
        return dict(status="ok", index_ready=(root / ".rag/index.json").is_file())

    @app.post("/query")
    async def ask(body: Question, authorization: str = Header("")):
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
        token = os.environ.get("RAG_QUERY_TOKEN", "")
        if not token or not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise Problem("UNAUTHORIZED", "Configure and supply RAG_QUERY_TOKEN.", 401)
        return await query(root, body.question)

    return app
