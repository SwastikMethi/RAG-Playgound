import pytest


@pytest.mark.asyncio
async def test_actual_cross_encoder_reranks_without_replacing_source_excerpts():
    from rag_runtime.reranker import rerank, MODEL, REVISION

    hits = [
        dict(candidate_id="a", excerpt="Apples grow in orchards.", rank=1, score=0.02, score_type="rrf"),
        dict(
            candidate_id="b",
            excerpt="Clock drift is fixed by synchronizing the system clock.",
            rank=2,
            score=0.01,
            score_type="rrf",
        ),
    ]
    result = await rerank(
        "How do I fix clock drift?",
        hits,
        dict(model=MODEL, model_revision=REVISION, max_input_tokens=512, device="cpu"),
    )
    assert result["candidates"][0]["candidate_id"] == "b"
    assert result["candidates"][0]["excerpt"] == hits[1]["excerpt"]
    assert all(isinstance(h["score"], float) and h["score_type"] == "reranker" for h in result["candidates"])
