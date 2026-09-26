import asyncio
from uuid import uuid4

import pytest

from rag_runtime.errors import Problem

pytestmark = pytest.mark.integration


def test_qdrant_queries_and_deletes_require_exact_immutable_scope():
    from rag_runtime.vectors import Scope, VectorStore

    store = VectorStore("http://127.0.0.1:6344", prefix="rag_test")
    project = uuid4().hex
    a, b = Scope(project, "corpus_a", "variant"), Scope(project, "corpus_b", "variant")
    chunks = [dict(candidate_id="a"), dict(candidate_id="b")]

    async def check():
        try:
            await store.put(a, chunks, [[1.0, 0.0], [0.0, 1.0]], 2)
            await store.put(b, [dict(candidate_id="foreign")], [[1.0, 0.0]], 2)
            hits = await store.search(a, [1.0, 0.0], 2, dict(mode="exact", hnsw_ef=None, min_score=None))
            assert [h["candidate_id"] for h in hits] == ["a", "b"]
            with pytest.raises(Problem):
                await store.search(None, [1.0, 0.0], 2, dict(mode="exact", hnsw_ef=None, min_score=None))
            await store.delete(a, 2)
            assert not await store.search(a, [1.0, 0.0], 2, dict(mode="exact", hnsw_ef=None, min_score=None))
            assert (await store.search(b, [1.0, 0.0], 2, dict(mode="exact", hnsw_ef=None, min_score=None)))[
                0
            ]["candidate_id"] == "foreign"
        finally:
            await store.delete(a, 2)
            await store.delete(b, 2)

    asyncio.run(check())
    store.close()
