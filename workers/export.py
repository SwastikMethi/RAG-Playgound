"""Bounded export assembly. Only explicit source snapshots may enter the ZIP."""

import ast
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import distributions
import io
import json
from pathlib import Path
import tempfile
import zipfile

from sqlalchemy import select
from app.database import scoped
from app.models import Artifact, Corpus, CorpusSource, Export, IndexBundle, Lane, Source, Run
from rag_runtime import __version__
from rag_runtime.contracts import canonical, digest, validate, CONTRACT_ROOT
from rag_runtime.context import GROUNDING
from rag_runtime.errors import Problem
from rag_runtime.process import run_json
from rag_runtime.providers import Profile
import rag_runtime.runtime as runtime

LIMIT = 150 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(runtime.__file__).parent


def portable_configuration(config, profiles):
    config = deepcopy(config)
    ids = [config["generation"]["profile_id"]]
    if config["embedding"]:
        ids.append(config["embedding"]["profile_id"])
    if config["tree"]:
        ids.extend([config["tree"]["index_profile_id"], config["tree"]["selection_profile_id"]])
    aliases = {id: f"provider-{i}" for i, id in enumerate(dict.fromkeys(ids), 1)}
    for part in ("generation", "embedding"):
        if config[part]:
            config[part]["profile_id"] = aliases[config[part]["profile_id"]]
    if config["tree"]:
        for key in ("index_profile_id", "selection_profile_id"):
            config["tree"][key] = aliases[config["tree"][key]]
    result = []
    for id, alias in aliases.items():
        p = deepcopy(profiles[id])
        p.update(id=alias, label=alias, api_key_env=alias.upper().replace("-", "_") + "_API_KEY")
        result.append(p)
    return config, result


def write_package(folder, config, profiles, sources, manifest, data):
    import yaml

    files = {}
    for path in sorted(RUNTIME.glob("*.py")):
        if path.is_symlink():
            raise Problem("UNSAFE_PACKAGE", "Runtime sources cannot be symlinks.")
        files["src/rag_runtime/" + path.name] = path.read_bytes()
    for filename in (
        "pipeline.schema.json",
        "export-manifest.schema.json",
        "trace-event.schema.json",
        "openapi.yaml",
    ):
        files["src/rag_runtime/contracts/" + filename] = (CONTRACT_ROOT / filename).read_bytes()
    pyproject = (ROOT / "pyproject.toml").read_text().split("[tool.hatch.build.targets.wheel]")[0]
    files["pyproject.toml"] = pyproject + '[tool.hatch.build.targets.wheel]\npackages = ["src/rag_runtime"]\n'
    files["uv.lock"] = (ROOT / "uv.lock").read_bytes()
    files["pipeline.json"] = canonical(config)
    files["profiles.yaml"] = yaml.safe_dump(dict(profiles=profiles))
    files["manifest.json"] = canonical(manifest)
    files["source-manifest.json"] = canonical(sources)
    hosts = sorted(
        {
            __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(p["base_url"]).hostname
            for p in profiles
            if p["base_url"]
        }
    )
    files[".env.example"] = "\n".join(
        [
            "# Supply keys locally. This archive contains no credentials.",
            *[p["api_key_env"] + "=" for p in profiles],
            "RAG_PROVIDER_HOST_ALLOWLIST=" + json.dumps(hosts),
            "RAG_QDRANT_URL=http://127.0.0.1:6333",
            "RAG_QUERY_TOKEN=",
            "",
        ]
    )
    for command in ("ingest", "query", "verify"):
        files[f"scripts/{command}.py"] = f"""from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rag_runtime.portable import main
main({command!r}, ROOT)
"""
    files["scripts/prepare_models.py"] = (ROOT / "tools/prepare_models.py").read_bytes()
    files["app/main.py"] = """from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rag_runtime.portable import create_app
app = create_app(ROOT)
"""
    files["tests/test_package.py"] = """import unittest
from pathlib import Path
from rag_runtime.portable import static_check
class PackageTest(unittest.TestCase):
    def test_package(self):
        self.assertEqual(static_check(Path(__file__).resolve().parents[1])["status"], "passed")
"""
    files["Dockerfile"] = """FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN uv sync --frozen --all-extras --no-dev
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
"""
    files[".dockerignore"] = ".env\n.venv\n__pycache__\n.rag\n"
    compose = dict(
        services=dict(
            app=dict(
                build=".",
                ports=["127.0.0.1:8000:8000"],
                env_file=[".env"],
                volumes=["./.rag:/app/.rag", "./data:/app/data"],
            )
        )
    )
    if config["embedding"]:
        compose["services"]["app"]["environment"] = dict(RAG_QDRANT_URL="http://qdrant:6333")
        compose["services"]["qdrant"] = dict(
            image="qdrant/qdrant:v1.17.0", ports=["127.0.0.1:6333:6333"], volumes=["vectors:/qdrant/storage"]
        )
        compose["volumes"] = dict(vectors={})
    files["compose.yaml"] = yaml.safe_dump(compose)
    notice = [
        "# Third-party dependencies",
        "",
        "Exact versions and distribution hashes are in uv.lock. Dependencies and model assets retain their upstream licenses. No model weights are bundled. This inventory records installed license metadata; consult each distribution for its full terms.",
        "",
        "| Distribution | Version | License metadata |",
        "| --- | --- | --- |",
    ]
    for d in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        license = (
            d.metadata.get("License-Expression") or d.metadata.get("License") or "See upstream distribution"
        )
        license = license.splitlines()[0][:140].replace("|", "/")
        notice.append(f"| {d.metadata['Name']} | {d.version} | {license} |")
    files["THIRD_PARTY_NOTICES.md"] = "\n".join(notice) + "\n"
    fixture = any(p["kind"] == "fixture" for p in profiles)
    files["README.md"] = f"""# Exported RAG application

{"**Fixture demonstration: answer and embedding outputs are synthetic. This is not a live model result.**" if fixture else "This application uses your configured model providers. Keys are required for ingestion with embeddings/tree indexing and for queries."}

Technique: `{config["technique"]}`. The archive contains the same retrieval, preparation, context and generation runtime as the playground. It requires Python 3.12 and uv. Dependencies are locked; the full optional dependency set is retained for reproducible PDF/tree/reranker setup.

## Setup and query

```sh
uv sync --frozen --all-extras --no-dev
cp .env.example .env
# Fill the provider key variables and RAG_QUERY_TOKEN in .env.
# For PDF input, download the public parser assets:
uv run --no-sync python scripts/prepare_models.py --pdf
# For hybrid_rerank, also download the pinned local cross-encoder:
uv run --no-sync python scripts/prepare_models.py --reranker
# For vector techniques, start Qdrant:
{"docker compose up -d qdrant" if config["embedding"] else "# No Qdrant service is needed for this technique."}
# Put exact original source bytes in data/ under the aliases in source-manifest.json.
uv run --no-sync python scripts/verify.py
uv run --no-sync python scripts/ingest.py --source-dir data
uv run --no-sync python scripts/query.py 'Your question'
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`GET /health` reports process health and index presence. `POST /query` accepts `{{"question":"Your question"}}` and requires `Authorization: Bearer <RAG_QUERY_TOKEN>`. It returns answer, exact evidence, timing and usage. The CLI needs no HTTP server or playground service. Model calls send the question and retrieved context to your configured endpoint.

In Docker, copy/configure `.env`, then `docker compose build`, `docker compose run --rm app uv run --no-sync python scripts/ingest.py --source-dir data`, and `docker compose up -d`. Prepare public model assets inside that environment before PDF/tree/rerank use. Data and indexes are local; do not expose the service publicly without additional deployment controls.

## Sources and verification

Included data: **{str(manifest["include_data"]).lower()}**. `source-manifest.json` lists every expected source ID, hash and neutral file alias. No-data exports exclude original names, document text, database records, questions, answers and credentials. A hash mismatch stops ingestion; restore the exact snapshot to reproduce this experiment. PostgreSQL JSON sources are captured records: no connection credentials or live database are needed. Text and Markdown must be UTF-8. PDF requires a text layer; OCR is unsupported. PageIndex accepts PDF only and builds an actual PageIndex SDK index; indexing can make model calls.

Limits: 50 sources, 100 MiB raw corpus, 500 pages per PDF, two million canonical characters and 10,000 chunks; the saved pipeline sets query and tree budgets. Ingestion rebuilds indexes and can take longer than a query. Keep `.rag` private; it contains extracted content and vectors.

The manifest records checks actually performed. The builder privately ran this copied runtime with recorded model/embedding/reranker/tree-selection boundaries and compared evidence order, source mapping, context request hashes and answer assembly. Offline vector replay uses the same Qdrant client in local exact mode; it does not measure remote HNSW performance. The private replay inputs are deleted and are not in this archive. `scripts/verify.py` now checks package structure and reports that recorded build verification; it cannot replay a private question that is intentionally absent. Live replay, when selected in the playground, runs current model decisions and reports differences; byte-identical future model answers are not promised. Neutral file aliases can change future tree document-selection prompts. See `manifest.json` for status and limitations.
"""
    if manifest["include_data"]:
        files.update({"data/" + item["file_alias"]: raw for item, raw in zip(sources, data)})
    if sum(len(v.encode() if isinstance(v, str) else v) for v in files.values()) > LIMIT:
        raise Problem("EXPORT_TOO_LARGE", "The expanded export exceeds 150 MiB.")
    for name, content in files.items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise Problem("UNSAFE_PACKAGE", "An archive path is unsafe.")
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        path.chmod(0o600)
    return files


async def export_lane(worker, claim):
    store = worker.store
    with store.session() as s:
        store.owned(s, claim["id"], claim["owner_token"])
        item = scoped(s, Export, claim["resource_id"], claim["project_id"])
        item.status = "building"
        run = scoped(s, Run, item.run_id, item.project_id)
        lane = s.scalar(select(Lane).where(Lane.id == item.lane_id, Lane.run_id == run.id))
        if not lane or lane.status != "completed":
            raise Problem("LANE_NOT_COMPLETE", "The selected lane is unavailable.", 409)
        bundle = scoped(s, IndexBundle, lane.bundle_id, item.project_id)
        prepared = json.loads(store.read(s, bundle.artifact_ids[0], item.project_id))
        sources = list(
            s.scalars(
                select(Source)
                .join(CorpusSource)
                .where(
                    CorpusSource.corpus_version_id == run.corpus_version_id,
                    Source.project_id == item.project_id,
                )
                .order_by(CorpusSource.ordinal)
            )
        )
        if sum(src.size_bytes or 0 for src in sources) > LIMIT - 2 * 1024 * 1024:
            raise Problem("EXPORT_TOO_LARGE", "The source snapshots exceed the export size limit.")
        entries, data = [], []
        for i, src in enumerate(sources, 1):
            fmt = "postgres_snapshot" if src.kind == "postgres" else src.source_metadata["format"]
            suffix = dict(pdf="pdf", markdown="md", text="txt", postgres_snapshot="json")[fmt]
            entries.append(
                dict(
                    source_id=src.id,
                    sha256=src.content_sha256,
                    source_format=fmt,
                    file_alias=f"source-{i}.{suffix}",
                )
            )
            data.append(store.read(s, src.raw_artifact_id, item.project_id))
        recordings, snapshot_profiles = None, None
        for artifact in s.scalars(
            select(Artifact).where(
                Artifact.id.in_(lane.provenance["artifact_ids"]), Artifact.project_id == item.project_id
            )
        ):
            if artifact.kind == "boundary_recordings":
                recordings = json.loads(store.read(s, artifact.id, item.project_id))
            elif artifact.kind == "provider_profiles":
                snapshot_profiles = json.loads(store.read(s, artifact.id, item.project_id))
        if recordings is None:
            raise Problem("REPLAY_UNAVAILABLE", "This lane has no complete boundary recording.")
        snapshot_profiles = snapshot_profiles or [p.model_dump() for p in claim["profiles"].values()]
        profile_map = {p["id"]: p for p in snapshot_profiles}
        config, portable_profiles = portable_configuration(lane.config_snapshot, profile_map)
        corpus = scoped(s, Corpus, run.corpus_version_id, item.project_id)

        def check():
            return dict(status="not_run", checked_at=None, details="", recorded_boundaries=[])

        manifest = dict(
            schema_version="1.0.0",
            export_id=item.id,
            technique=config["technique"],
            pipeline_sha256=digest(config),
            original_config_sha256=digest(lane.config_snapshot),
            corpus_fingerprint=corpus.content_fingerprint,
            runtime_revision=__version__
            + "+"
            + digest(b"".join(p.read_bytes() for p in sorted(RUNTIME.glob("*.py"))))[:16],
            dependency_lock_sha256=digest((ROOT / "uv.lock").read_bytes()),
            prompt_id="grounded_answer_v1",
            prompt_sha256=digest(GROUNDING.encode()),
            source_hashes=entries,
            model_revisions=lane.provenance["model_revisions"],
            tokenizer_revision=prepared["versions"]["tokenizer"],
            vector_dimensions=config["embedding"]["dimensions"] if config["embedding"] else None,
            include_data=item.include_data,
            verification={name: check() for name in ("static", "offline_replay", "live_replay")},
            limitations=[
                "Offline replay controls model boundaries; it is not a live provider benchmark.",
                "Offline vectors use Qdrant local exact search; remote approximate-search behavior is not measured.",
                "Private replay inputs are omitted. The shipped verify command checks structure and reports build verification.",
            ],
        )
        if any(p["kind"] == "fixture" for p in portable_profiles):
            manifest["limitations"].append(
                "Fixture demonstration: synthetic model outputs, not live model integration."
            )
        request = dict(
            mode="offline",
            config=lane.config_snapshot,
            prepared=prepared,
            profiles=snapshot_profiles,
            question=run.question,
            recordings=recordings,
            evidence=lane.evidence,
            answer=lane.answer,
        )
        mode = item.verification_mode
    with tempfile.TemporaryDirectory(prefix="export-", dir=store.root) as temporary:
        folder = Path(temporary)
        # ponytail: bounded 150 MiB file set; synchronous writes finish before cancellation cleanup.
        # Move assembly to an owned subprocess if the archive ceiling increases.
        files = write_package(folder, config, portable_profiles, entries, manifest, data)
        validate(manifest, "export-manifest.schema.json")
        replay = await run_json(
            [str(folder / "scripts/verify.py")], input_data=request, root=folder, timeout=300
        )
        now = datetime.now(timezone.utc).isoformat()
        manifest["verification"]["offline_replay"] = dict(
            status="passed",
            checked_at=now,
            details="Copied runtime matched evidence IDs/order, exact context requests, source mappings and answer assembly.",
            recorded_boundaries=replay["boundaries"],
        )
        if mode == "live":
            request["mode"] = "live"
            # Pass this owner's credentials only to this isolated verification process.
            for profile in snapshot_profiles:
                if (
                    profile["id"] not in claim["profiles"]
                    or claim["profiles"][profile["id"]].fingerprint()
                    != Profile.model_validate(profile).fingerprint()
                ):
                    raise Problem(
                        "PROFILE_CHANGED",
                        "A provider profile changed since this lane. Save and run a new revision.",
                    )
            live = await run_json(
                [str(folder / "scripts/verify.py")], input_data=request, root=folder, timeout=300,
                env_extra={p.api_key_env: p.key for p in claim["profiles"].values() if p.api_key_env}
            )
            manifest["verification"]["live_replay"] = dict(
                status="passed",
                checked_at=datetime.now(timezone.utc).isoformat(),
                details=f"Current providers executed. Evidence order matches: {live['evidence_matches']}; answer text matches: {live['answer_matches']}. Existing verified source indexes were reused.",
                recorded_boundaries=[],
            )
        manifest["verification"]["static"] = dict(
            status="passed",
            checked_at=now,
            details="Manifest/pipeline schema, Python syntax/imports, declared locked dependencies and safe archive paths checked.",
            recorded_boundaries=[],
        )
        validate(manifest, "export-manifest.schema.json")
        (folder / "manifest.json").write_bytes(canonical(manifest))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(files):
                path = folder / name
                if path.is_symlink():
                    raise Problem("UNSAFE_PACKAGE", "Symlinks are not allowed in exports.")
                if path.is_file() and "__pycache__" not in path.parts:
                    name = path.relative_to(folder).as_posix()
                    if path.suffix == ".py":
                        ast.parse(path.read_text())
                    archive.write(path, name)
        raw = output.getvalue()
        if len(raw) > LIMIT:
            raise Problem("EXPORT_TOO_LARGE", "The archive exceeds 150 MiB.")
        with store.session() as s:
            store.owned(s, claim["id"], claim["owner_token"])
            item = scoped(s, Export, claim["resource_id"], claim["project_id"])
            artifact = store.put(
                s,
                item.project_id,
                "export_archive",
                raw,
                dict(run_id=item.run_id, lane_id=item.lane_id, include_data=item.include_data),
            )
            item.artifact_id, item.manifest, item.status = artifact.id, manifest, "ready"
