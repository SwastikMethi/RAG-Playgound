"""The query entry point used unchanged by the worker and exported applications."""

import time
from uuid import uuid4

from .chunking import lexical_tokens, token_count
from .context import GROUNDING, INSUFFICIENT, citation_status, pack_context
from .contracts import digest
from .errors import Problem
from .providers import empty_usage
from .registry import resolve_profile
from .retrieval import bm25_search
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
    trace = Trace(emit)
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
        if config["technique"] != "bm25":
            raise Problem("UNSUPPORTED_TECHNIQUE", "This adapter is not installed.")
        async with trace.span(
            "lexical_search", retrieval.id, dict(query_terms=lexical_tokens(question)[:1000])
        ) as search:
            candidates = bm25_search(
                question, prepared["chunks"], config["search"]["candidate_k"], config["search"]["bm25"]
            )
            search.details = dict(input_count=len(prepared["chunks"]), output_count=len(candidates))
            await emit(
                "retrieval.candidates", dict(span_id=search.id, stage="lexical_search", candidates=candidates)
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
            result["usage"] = output_usage or dict(
                empty_usage(),
                input_tokens=token_count(str(messages), tokenizer),
                output_tokens=token_count(result["answer"], tokenizer),
                accounting="estimated",
            )
            result["recordings"].append(
                dict(
                    operation="generation",
                    request_sha256=digest(dict(config=generation, messages=messages)),
                    response=result["answer"],
                    usage=result["usage"],
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
                    usage=result["usage"],
                ),
            )
        result["metrics"].update(
            generation_ms=generation_span.duration_ms, provider_wait_ms=generation_span.wait_ms
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
