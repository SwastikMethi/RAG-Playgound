"""Real retrieval operations shared by the worker and exported runtime."""

from rank_bm25 import BM25Okapi
from functools import lru_cache

from .chunking import lexical_tokens


@lru_cache(maxsize=2)
def lexical_index(documents, k1, b, epsilon):
    # Two bounded corpus inputs, never serialized executable model objects or cached answers.
    return BM25Okapi(documents, k1=k1, b=b, epsilon=epsilon)


def bm25_search(question: str, chunks: list[dict], limit: int, config: dict) -> list[dict]:
    query = lexical_tokens(question)
    documents = tuple(tuple(lexical_tokens(c["excerpt"])) for c in chunks)
    if not query or not any(documents):
        return []
    scores = lexical_index(documents, config["k1"], config["b"], config["epsilon"]).get_scores(query)
    matches = [(i, set(query).intersection(tokens)) for i, tokens in enumerate(documents)]
    order = sorted(
        (i for i, overlap in matches if overlap), key=lambda i: (-float(scores[i]), chunks[i]["candidate_id"])
    )[:limit]
    return [
        dict(
            chunks[i],
            score=float(scores[i]),
            score_type="bm25",
            rank=rank,
            branch_ranks=dict(lexical=rank, dense=None),
            matched_terms=sorted(matches[i][1]),
        )
        for rank, i in enumerate(order, 1)
    ]


def fuse(lexical: list[dict], dense: list[dict], limit: int, k: int = 60) -> list[dict]:
    merged = {}
    for branch, hits in (("lexical", lexical), ("dense", dense)):
        for rank, hit in enumerate(hits, 1):
            key = hit["candidate_id"]
            if key not in merged:
                merged[key] = dict(
                    hit, score=0.0, score_type="rrf", branch_ranks=dict(lexical=None, dense=None)
                )
            merged[key]["score"] += 1 / (k + rank)
            merged[key]["branch_ranks"][branch] = rank
    return [
        dict(hit, rank=rank)
        for rank, hit in enumerate(
            sorted(merged.values(), key=lambda h: (-h["score"], h["candidate_id"]))[:limit], 1
        )
    ]


def expand_parents(hits: list[dict], parents: list[dict]) -> list[dict]:
    lookup, result = {p["candidate_id"]: p for p in parents}, {}
    for hit in hits:
        key = hit["parent_id"]
        if key not in result:
            result[key] = dict(
                lookup[key],
                score=hit["score"],
                score_type=hit["score_type"],
                rank=len(result) + 1,
                child_ids=[],
                parent_id=key,
            )
        result[key]["child_ids"].append(hit["candidate_id"])
    return list(result.values())
