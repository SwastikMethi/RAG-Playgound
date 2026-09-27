"""Qdrant access has no unscoped entry point."""

import asyncio
import math
from dataclasses import asdict, dataclass
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from .contracts import canonical
from .errors import Problem


@dataclass(frozen=True)
class Scope:
    project_id: str
    corpus_version_id: str
    variant_fingerprint: str

    def filter(self):
        if not all(isinstance(v, str) and v for v in asdict(self).values()):
            raise Problem("VECTOR_SCOPE", "A complete immutable vector scope is required.")
        return models.Filter(
            must=[
                models.FieldCondition(key=k, match=models.MatchValue(value=v))
                for k, v in asdict(self).items()
            ]
        )


def require_scope(scope):
    if not isinstance(scope, Scope):
        raise Problem("VECTOR_SCOPE", "A complete immutable vector scope is required.")
    return scope.filter()


def check_vectors(vectors, dimensions):
    for vector in vectors:
        if len(vector) != dimensions or not all(
            isinstance(v, (int, float)) and math.isfinite(v) for v in vector
        ):
            raise Problem(
                "EMBEDDING_DIMENSION", "The embedding dimension or values do not match the model profile."
            )
        if not any(vector):
            raise Problem("INVALID_EMBEDDING", "The provider returned a zero-length embedding vector.")


class VectorStore:
    def __init__(self, url, prefix="rag_v1", api_key=None):
        self.client = (
            QdrantClient(location=":memory:")
            if url == ":memory:"
            else QdrantClient(url=url, api_key=api_key or None, timeout=20)
        )
        self.prefix = prefix

    def collection(self, dimensions):
        return f"{self.prefix}_cosine_{dimensions}"

    def close(self):
        self.client.close()

    async def put(self, scope: Scope, chunks, vectors, dimensions):
        require_scope(scope)
        check_vectors(vectors, dimensions)
        if len(vectors) != len(chunks):
            raise Problem("EMBEDDING_COUNT", "The embedding response did not match the number of passages.")
        collection = self.collection(dimensions)
        if not await asyncio.to_thread(self.client.collection_exists, collection):
            try:
                await asyncio.to_thread(
                    self.client.create_collection,
                    collection,
                    vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE, on_disk=True),
                    hnsw_config=models.HnswConfigDiff(on_disk=True),
                )
            except UnexpectedResponse as exc:
                if exc.status_code != 409:
                    raise
            for key in asdict(scope):
                await asyncio.to_thread(
                    self.client.create_payload_index,
                    collection,
                    key,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
        for start in range(0, len(chunks), 128):
            points = [
                models.PointStruct(
                    id=str(
                        uuid5(
                            NAMESPACE_URL,
                            canonical(dict(**asdict(scope), candidate_id=chunk["candidate_id"])).decode(),
                        )
                    ),
                    vector=vector,
                    payload=dict(**asdict(scope), candidate_id=chunk["candidate_id"]),
                )
                for chunk, vector in zip(chunks[start : start + 128], vectors[start : start + 128])
            ]
            writing = asyncio.create_task(
                asyncio.to_thread(self.client.upsert, collection, points=points, wait=True)
            )
            try:
                await asyncio.shield(writing)
            except asyncio.CancelledError:
                # A thread cannot be cancelled. Finish the bounded write before its owner deletes this scope.
                await writing
                raise

    async def search(self, scope: Scope, vector, limit, settings):
        filter = require_scope(scope)
        check_vectors([vector], len(vector))
        collection = self.collection(len(vector))
        if not await asyncio.to_thread(self.client.collection_exists, collection):
            raise Problem("INDEX_MISSING", "The prepared vector index is unavailable. Prepare it again.", 409)
        # ponytail: at most 10,000 compact IDs; collect the bounded corpus to break cutoff ties deterministically.
        # Replace with score-boundary pagination only when the corpus ceiling increases.
        result = await asyncio.to_thread(
            self.client.query_points,
            collection_name=collection,
            query=vector,
            query_filter=filter,
            search_params=models.SearchParams(exact=settings["mode"] == "exact", hnsw_ef=settings["hnsw_ef"]),
            limit=10_000,
            with_payload=["candidate_id"],
            score_threshold=settings["min_score"],
        )
        hits = sorted(result.points, key=lambda hit: (-hit.score, hit.payload["candidate_id"]))[:limit]
        return [
            dict(candidate_id=hit.payload["candidate_id"], score=float(hit.score), rank=rank)
            for rank, hit in enumerate(hits, 1)
        ]

    async def delete(self, scope: Scope, dimensions):
        filter = require_scope(scope)
        collection = self.collection(dimensions)
        if await asyncio.to_thread(self.client.collection_exists, collection):
            await asyncio.to_thread(
                self.client.delete,
                collection,
                points_selector=models.FilterSelector(filter=filter),
                wait=True,
            )
