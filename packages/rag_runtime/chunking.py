"""Portable chunk identities. Offsets always count Unicode code points."""

import re
import unicodedata
from functools import lru_cache

import tiktoken

from .contracts import digest
from .errors import Problem


@lru_cache
def encoding(name: str):
    try:
        return tiktoken.get_encoding(name)
    except ValueError:
        raise Problem("UNSUPPORTED_TOKENIZER", "The configured tokenizer is not installed.") from None


def token_count(text: str, tokenizer: str) -> int:
    return len(encoding(tokenizer).encode(text, disallowed_special=()))


def lexical_tokens(text: str) -> list[str]:
    return re.findall(r"\w+(?:[-’']\w+)*", unicodedata.normalize("NFKC", text).casefold())


def token_spans(text: str, size: int, overlap: int, tokenizer: str):
    enc = encoding(tokenizer)
    tokens = enc.encode(text, disallowed_special=())
    _, offsets = enc.decode_with_offsets(tokens)
    offsets.append(len(text))
    cursor = 0
    while cursor < len(tokens):
        end = min(cursor + size, len(tokens))
        # A token may end inside a multi-token Unicode character. Only emit whole characters.
        while end > cursor and token_count(text[offsets[cursor] : offsets[end]], tokenizer) > size:
            end -= 1
        if end == cursor or offsets[end] <= offsets[cursor]:
            raise Problem("CHUNKING_FAILED", "A character cannot fit in the configured token window.")
        yield offsets[cursor], offsets[end]
        if end == len(tokens):
            break
        next_cursor = max(cursor + 1, end - overlap)
        while next_cursor < len(tokens) and offsets[next_cursor] <= offsets[cursor]:
            next_cursor += 1
        cursor = next_cursor


def heading_spans(text: str, start: int, end: int):
    boundaries, offset, fence = [start], start, None
    for line in text[start:end].splitlines(keepends=True):
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            mark = match[1][0]
            fence = mark if fence is None else (None if fence == mark else fence)
        elif fence is None and re.match(r"^#{1,6}\s", line) and offset > start:
            boundaries.append(offset)
        offset += len(line)
    boundaries.append(end)
    return zip(boundaries, boundaries[1:])


def evidence_span(source: dict, start: int, end: int, segment: dict, identity: dict) -> dict:
    candidate = digest(
        dict(
            source=source["source_id"],
            content=source["sha256"],
            parser=[source["parser"], source["parser_revision"]],
            start=start,
            end=end,
            text=source["text"][start:end],
            **identity,
        )
    )
    text, page = source["text"], segment.get("page")
    kind = "database" if segment.get("record_key") is not None else ("pdf" if page else "text")
    return dict(
        evidence_id=candidate,
        candidate_id=candidate,
        source_id=source["source_id"],
        source_name=source["name"],
        excerpt=text[start:end],
        location=dict(
            kind=kind,
            page_start=page,
            page_end=page,
            char_start=start,
            char_end=end,
            line_start=text.count("\n", 0, start) + 1,
            line_end=text.count("\n", 0, max(start, end - 1)) + 1,
            relation=segment.get("relation"),
            record_key=segment.get("record_key"),
        ),
        label=None,
        score=None,
        score_type="none",
        rank=1,
        branch_ranks=dict(lexical=None, dense=None),
        included_in_context=False,
        span_truncated=False,
    )


def chunk_source(source: dict, config: dict) -> list[dict]:
    chunks = []
    for segment in source["segments"]:
        spans = (
            heading_spans(source["text"], segment["start"], segment["end"])
            if config["strategy"] == "headings"
            else [(segment["start"], segment["end"])]
        )
        for a, b in spans:
            for left, right in token_spans(
                source["text"][a:b], config["size_tokens"], config["overlap_tokens"], config["tokenizer"]
            ):
                if source["text"][a + left : a + right].strip():
                    chunks.append(evidence_span(source, a + left, a + right, segment, dict(chunking=config)))
    if len(chunks) > 10_000:
        raise Problem("TOO_MANY_CHUNKS", "The corpus may contain at most 10,000 chunks.")
    return chunks


def parent_child_chunks(source: dict, child_config: dict, max_parent_tokens: int):
    parents = chunk_source(source, dict(child_config, size_tokens=max_parent_tokens, overlap_tokens=0))
    children = []
    for parent in parents:
        start, end = parent["location"]["char_start"], parent["location"]["char_end"]
        segment = next(s for s in source["segments"] if s["start"] <= start and end <= s["end"])
        for a, b in token_spans(
            source["text"][start:end],
            child_config["size_tokens"],
            child_config["overlap_tokens"],
            child_config["tokenizer"],
        ):
            child = evidence_span(
                source,
                start + a,
                start + b,
                segment,
                dict(chunking=child_config, parent_id=parent["candidate_id"]),
            )
            children.append(dict(child, parent_id=parent["candidate_id"]))
    return children, parents
