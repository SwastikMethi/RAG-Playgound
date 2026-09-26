import asyncio
import time
from types import SimpleNamespace

import pytest

from rag_runtime.chunking import chunk_source
from rag_runtime.providers import Gateway, load_profiles
from rag_runtime.registry import defaults
from rag_runtime.runtime import execute
from tests.unit.test_runtime import source


@pytest.mark.asyncio
async def test_hybrid_wall_time_is_parallel_not_the_sum_of_its_branches(monkeypatch):
    from rag_runtime import runtime

    profiles = load_profiles(SimpleNamespace(mode="test"))
    config = defaults("hybrid", profiles)
    chunks = chunk_source(source("The clock must be synchronized."), config["chunking"])
    gateway = Gateway()
    real_embed = gateway.embed

    async def embed(*args):
        await asyncio.sleep(0.2)
        return await real_embed(*args)

    gateway.embed = embed
    real_search = runtime.bm25_search

    def search(*args):
        time.sleep(0.15)
        return real_search(*args)

    monkeypatch.setattr(runtime, "bm25_search", search)

    class Vectors:
        async def search(self, *args):
            return [dict(candidate_id=chunks[0]["candidate_id"], score=0.8, rank=1)]

    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    result = await execute(
        "How do I fix the clock?",
        config,
        dict(
            chunks=chunks,
            parents=[],
            scope=dict(project_id="p", corpus_version_id="c", variant_fingerprint="v"),
        ),
        profiles,
        gateway,
        emit,
        vector_store=Vectors(),
    )
    durations = {p["stage"]: p["duration_ms"] for kind, p in events if kind == "stage.completed"}
    assert result["metrics"]["retrieval_ms"] >= max(durations["lexical_search"], durations["query_embedding"])
    assert result["metrics"]["retrieval_ms"] < durations["lexical_search"] + durations["query_embedding"] - 70
    assert result["metrics"]["ttft_ms"] >= result["metrics"]["retrieval_ms"]
