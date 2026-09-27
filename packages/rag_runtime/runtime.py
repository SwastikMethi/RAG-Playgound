"""The query entry point used unchanged by the worker and exported applications."""

import time
import asyncio
from uuid import uuid4

from .chunking import lexical_tokens, token_count
from .context import GROUNDING, INSUFFICIENT, citation_status, pack_context
from .contracts import digest
from .errors import Problem
from .providers import empty_usage, add_usage
from .registry import resolve_profile
from .retrieval import bm25_search, fuse, expand_parents
from .reranker import rerank
from .vectors import Scope
from .trace import Trace, empty_timing


async def execute(
    question: str,
    config: dict,
    prepared: dict,
    profiles: dict,
    gateway,
    emit,
    result: dict | None = None,
    vector_store=None,
    started: float | None = None,
    rerank_fn=rerank,
) -> dict:
    result = result if result is not None else {}
    result.update(
        answer="",
        evidence=[],
        answer_kind="answer",
        metrics=empty_timing(),
        usage=empty_usage(),
        recordings=[],
        warnings=[],
    )
    began = started if started is not None else time.monotonic()
    trace = Trace(emit, result["metrics"])
    generation = config["generation"]
    profile = resolve_profile(profiles, generation["profile_id"], generation["model"], "generation")
    tokenizer = profile.tokenizer
    if (
        token_count(GROUNDING + question, tokenizer)
        + generation["context_budget_tokens"]
        + generation["max_output_tokens"]
        + 64
        > profile.max_input_tokens
    ):
        raise Problem(
            "MODEL_INPUT_LIMIT", "The question and configured context exceed this model's token limit."
        )
    async with trace.span("retrieval", details=dict(input_count=len(prepared["chunks"]))) as retrieval:

        async def lexical():
            async with trace.span(
                "lexical_search", retrieval.id, dict(query_terms=lexical_tokens(question)[:1000])
            ) as search:
                hits = await asyncio.to_thread(
                    bm25_search,
                    question,
                    prepared["chunks"],
                    config["search"]["candidate_k"],
                    config["search"]["bm25"],
                )
                search.details = dict(input_count=len(prepared["chunks"]), output_count=len(hits))
                await emit(
                    "retrieval.candidates", dict(span_id=search.id, stage="lexical_search", candidates=hits)
                )
                return hits

        async def dense():
            emb = config["embedding"]
            p = resolve_profile(profiles, emb["profile_id"], emb["model"], "embedding")
            async with trace.span(
                "query_embedding", retrieval.id, dict(model=p.model, dimensions=p.dimensions)
            ) as embedding:
                result["provider_attempted"] = True
                vector = await gateway.embed(p, [emb["query_prefix"] + question])
                embedding.wait_ms = vector["wait_ms"]
                result["metrics"]["provider_wait_ms"] = (result["metrics"]["provider_wait_ms"] or 0) + vector[
                    "wait_ms"
                ]
                result["recordings"].append(vector["recording"])
                result["usage"] = vector["usage"]
                await emit(
                    "usage.recorded",
                    dict(
                        call_id=uuid4().hex,
                        operation="embedding",
                        profile_id=p.id,
                        model=p.model,
                        usage=vector["usage"],
                    ),
                )
                embedding.details = dict(output_count=1, dimensions=p.dimensions)
            async with trace.span("dense_search", retrieval.id) as search:
                if vector_store is None:
                    raise Problem("INDEX_MISSING", "The prepared vector store is unavailable.", 409)
                matches = await vector_store.search(
                    Scope(**prepared["scope"]),
                    vector["vectors"][0],
                    config["search"]["candidate_k"],
                    config["search"]["dense"],
                )
                lookup = {chunk["candidate_id"]: chunk for chunk in prepared["chunks"]}
                if any(match["candidate_id"] not in lookup for match in matches):
                    raise Problem(
                        "INDEX_CORRUPT", "A vector result does not belong to the prepared chunk manifest."
                    )
                hits = [
                    dict(
                        lookup[hit["candidate_id"]],
                        score=hit["score"],
                        rank=hit["rank"],
                        score_type="cosine",
                        branch_ranks=dict(lexical=None, dense=hit["rank"]),
                    )
                    for hit in matches
                ]
                search.details = dict(
                    input_count=len(prepared["chunks"]),
                    output_count=len(hits),
                    summary=f"Cosine similarity; {config['search']['dense']['mode']} Qdrant search.",
                )
                await emit(
                    "retrieval.candidates", dict(span_id=search.id, stage="dense_search", candidates=hits)
                )
                return hits

        if config["tree"]:
            from .pageindex_adapter import retrieve_tree

            candidates = await retrieve_tree(
                question,
                prepared["documents"],
                config["tree"],
                profiles,
                gateway,
                trace,
                retrieval.id,
                result,
            )
            await emit(
                "retrieval.candidates", dict(span_id=retrieval.id, stage="retrieval", candidates=candidates)
            )
        elif config["search"]["rrf"]:
            branches = [asyncio.create_task(lexical()), asyncio.create_task(dense())]
            try:
                lexical_hits, dense_hits = await asyncio.gather(*branches)
            except BaseException:
                for branch in branches:
                    branch.cancel()
                await asyncio.gather(*branches, return_exceptions=True)
                raise
            async with trace.span("fusion", retrieval.id) as fusion:
                candidates = fuse(
                    lexical_hits, dense_hits, config["search"]["candidate_k"], config["search"]["rrf"]["k"]
                )
                fusion.details = dict(
                    input_count=len(lexical_hits) + len(dense_hits),
                    output_count=len(candidates),
                    summary=f"Equal reciprocal rank fusion, k={config['search']['rrf']['k']}.",
                )
                await emit(
                    "retrieval.candidates", dict(span_id=fusion.id, stage="fusion", candidates=candidates)
                )
        elif config["embedding"]:
            candidates = await dense()
        else:
            candidates = await lexical()
        if config["reranker"]:
            async with trace.span(
                "rerank", retrieval.id, dict(model=config["reranker"]["model"])
            ) as reranking:
                before = {c["candidate_id"]: c["rank"] for c in candidates}
                ranked = await rerank_fn(question, candidates, config["reranker"])
                candidates = ranked["candidates"]
                reranking.wait_ms = ranked["wait_ms"]
                reranking.details = dict(
                    input_count=len(before),
                    output_count=len(candidates),
                    summary=f"English cross-encoder; at most {config['reranker']['max_input_tokens']} scoring tokens. Original excerpts retained.",
                )
                if ranked["recording"]:
                    result["recordings"].append(ranked["recording"])
                await emit(
                    "rerank.completed",
                    dict(
                        span_id=reranking.id,
                        model=config["reranker"]["model"],
                        changes=[
                            dict(
                                candidate_id=c["candidate_id"],
                                before_rank=before[c["candidate_id"]],
                                after_rank=c["rank"],
                                score=c["score"],
                            )
                            for c in candidates
                        ],
                    ),
                )
        if config["parent"]:
            async with trace.span("parent_expansion", retrieval.id) as expansion:
                count = len(candidates)
                candidates = expand_parents(candidates, prepared["parents"])
                expansion.details = dict(input_count=count, output_count=len(candidates))
                await emit(
                    "retrieval.candidates",
                    dict(span_id=expansion.id, stage="parent_expansion", candidates=candidates),
                )
        retrieval.details = dict(output_count=len(candidates))
    result["metrics"]["retrieval_ms"] = retrieval.duration_ms
    async with trace.span("context_packing", details=dict(input_count=len(candidates))) as context:
        packed = pack_context(
            candidates, config["search"]["context_k"], generation["context_budget_tokens"], tokenizer
        )
        result["evidence"] = packed["evidence"]
        included = {e["candidate_id"] for e in result["evidence"]}
        await emit(
            "context.selected",
            dict(
                span_id=context.id,
                evidence=packed["evidence"],
                excluded_candidate_ids=[
                    c["candidate_id"] for c in candidates if c["candidate_id"] not in included
                ],
                token_count=packed["token_count"],
                token_count_kind="exact",
                budget_tokens=generation["context_budget_tokens"],
            ),
        )
        context.details = dict(output_count=len(packed["evidence"]))
    result["metrics"]["context_ms"] = context.duration_ms
    if not packed["evidence"]:
        result["answer_kind"], result["answer"] = "insufficient_evidence", INSUFFICIENT
        await emit(
            "stage.skipped",
            dict(span_id=uuid4().hex, stage="generation", reason="No supporting evidence was retrieved."),
        )
        await emit("answer.delta", dict(text=INSUFFICIENT, offset_chars=0))
    else:
        messages = [
            dict(role="system", content=GROUNDING),
            dict(
                role="user",
                content=f"<question>\n{question}\n</question>\n<evidence>{packed['text']}\n</evidence>",
            ),
        ]
        async with trace.span("generation", details=dict(model=profile.model)) as generation_span:
            output_usage = None
            result["provider_attempted"] = True
            async for frame in gateway.stream(profile, generation, messages):
                if "wait_ms" in frame:
                    generation_span.wait_ms += frame["wait_ms"]
                if frame.get("retry"):
                    await emit(
                        "warning",
                        dict(
                            code="PROVIDER_RETRY",
                            message="The provider failed before answer text. Retrying once.",
                        ),
                    )
                if "usage" in frame:
                    output_usage = frame["usage"]
                if "text" in frame:
                    if result["metrics"]["ttft_ms"] is None:
                        result["metrics"]["ttft_ms"] = (time.monotonic() - began) * 1000
                    offset = len(result["answer"])
                    if offset + len(frame["text"]) > 200_000:
                        raise Problem("ANSWER_LIMIT", "The provider exceeded the answer size limit.")
                    result["answer"] += frame["text"]
                    # Persistence coalescing is owned by the writer; timing is captured before that boundary.
                    for start in range(0, len(frame["text"]), 16000):
                        await emit(
                            "answer.delta",
                            dict(text=frame["text"][start : start + 16000], offset_chars=offset + start),
                        )
            if not result["answer"]:
                raise Problem("EMPTY_ANSWER", "The model provider returned no answer text.", 502)
            generation_usage = output_usage or dict(
                empty_usage(),
                input_tokens=token_count(str(messages), tokenizer),
                output_tokens=token_count(result["answer"], tokenizer),
                accounting="estimated",
            )
            add_usage(result["usage"], generation_usage)
            result["recordings"].append(
                dict(
                    operation="generation",
                    request_sha256=digest(dict(config=generation, messages=messages)),
                    response=result["answer"],
                    usage=generation_usage,
                    profile_fingerprint=profile.fingerprint(),
                )
            )
            await emit(
                "usage.recorded",
                dict(
                    call_id=uuid4().hex,
                    operation="generation",
                    profile_id=profile.id,
                    model=profile.model,
                    usage=generation_usage,
                ),
            )
        result["metrics"].update(
            generation_ms=generation_span.duration_ms,
            provider_wait_ms=(result["metrics"]["provider_wait_ms"] or 0) + generation_span.wait_ms,
        )
    citations = citation_status(result["answer"], result["evidence"])
    if result["answer_kind"] == "answer" and not citations["valid"]:
        warning = "Citation labels are missing or invalid. This check does not verify that the sources support the answer."
        result["warnings"].append(warning)
        await emit("warning", dict(code="CITATION_LABELS", message=warning))
    await emit(
        "answer.completed",
        dict(
            answer_kind=result["answer_kind"],
            text_sha256=digest(result["answer"].encode()),
            valid_citation_labels=sorted(set(citations["cited_labels"]) - set(citations["unknown_labels"])),
            invalid_citation_labels=citations["unknown_labels"],
        ),
    )
    result["metrics"]["total_ms"] = (time.monotonic() - began) * 1000
    return result
