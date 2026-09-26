"""Real retrieval and span tests; only external model calls are deterministic."""
import hashlib

import pytest


def source(text, source_id="source_one"):
    return dict(source_id=source_id, name="source.md", format="markdown", text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                segments=[dict(start=0, end=len(text), page=None)], parser="utf8", parser_revision="1")


def test_unicode_chunks_keep_exact_source_spans_and_identifiers():
    from rag_runtime.chunking import chunk_source, lexical_tokens
    text = "# Heading\n" + ("Orbit 🪐 café 日本語 NEBULA-42. " * 90)
    chunks = chunk_source(source(text), dict(strategy="fixed_tokens", size_tokens=64,
                                           overlap_tokens=8, tokenizer="cl100k_base", tokenizer_revision="1"))
    assert len(chunks) > 1
    for chunk in chunks:
        loc = chunk["location"]
        assert text[loc["char_start"]:loc["char_end"]] == chunk["excerpt"]
        assert "�" not in chunk["excerpt"]
    assert "nebula-42" in lexical_tokens("ＮＥＢＵＬＡ-42")
    assert chunks[0]["candidate_id"] == chunk_source(source(text), dict(strategy="fixed_tokens", size_tokens=64,
                overlap_tokens=8, tokenizer="cl100k_base", tokenizer_revision="1"))[0]["candidate_id"]


def test_actual_bm25_filters_zero_overlap_and_rrf_ties_are_stable():
    from rag_runtime.retrieval import bm25_search, fuse
    from rag_runtime.chunking import chunk_source
    cfg = dict(strategy="fixed_tokens", size_tokens=64, overlap_tokens=8, tokenizer="cl100k_base", tokenizer_revision="1")
    chunks = chunk_source(source("NEBULA-42 is a clock synchronization error."), cfg)
    chunks += chunk_source(source("Apples grow on trees.", "source_two"), cfg)
    result = bm25_search("NEBULA-42", chunks, 20, dict(k1=1.5,b=0.75,epsilon=.25))
    assert [c["source_id"] for c in result] == ["source_one"]
    assert bm25_search("zyxwvu", chunks, 20, dict(k1=1.5,b=.75,epsilon=.25)) == []
    a, b = dict(chunks[0], candidate_id="a", rank=1), dict(chunks[1], candidate_id="b", rank=2)
    merged = fuse([a,b], [dict(b,rank=1),dict(a,rank=2)], 20, 60)
    assert [x["candidate_id"] for x in merged] == ["a","b"]
    assert merged[0]["score"] == pytest.approx(1/61+1/62)
    assert merged[0]["branch_ranks"] == {"lexical":1,"dense":2}


def test_context_clipping_preserves_supplied_spans_and_budget():
    from rag_runtime.chunking import chunk_source, token_count
    from rag_runtime.context import pack_context
    text = "Synchronization fixes clock errors. " * 100
    chunks = chunk_source(source(text), dict(strategy="fixed_tokens",size_tokens=512,
                          overlap_tokens=64,tokenizer="cl100k_base",tokenizer_revision="1"))
    packed = pack_context(chunks, 5, 100, "cl100k_base")
    assert packed["token_count"] <= 100
    assert packed["evidence"][0]["span_truncated"]
    for item in packed["evidence"]:
        assert text[item["location"]["char_start"]:item["location"]["char_end"]] == item["excerpt"]
    assert token_count(packed["text"], "cl100k_base") <= 100


def test_parent_expansion_keeps_one_parent_and_child_links():
    from rag_runtime.chunking import parent_child_chunks
    from rag_runtime.retrieval import expand_parents
    children, parents = parent_child_chunks(source("A long section. " * 500),
                   dict(strategy="fixed_tokens",size_tokens=64,overlap_tokens=8,tokenizer="cl100k_base",tokenizer_revision="1"), 256)
    hits = [dict(c,rank=i+1,score=.8,score_type="cosine") for i,c in enumerate(children[:2])]
    result = expand_parents(hits, parents)
    assert len(result) == 1
    assert result[0]["child_ids"] == [c["candidate_id"] for c in hits]


def test_parser_rejects_invalid_utf8_and_preserves_lines(tmp_path):
    from rag_runtime.parsing import parse_file
    from rag_runtime.errors import Problem
    path = tmp_path / "text"
    path.write_bytes(b"hello\xff")
    with pytest.raises(Problem):
        parse_file(path,"text")
    path.write_text("Hello 🪐\nNext line.")
    result = parse_file(path,"text")
    assert result["text"] == "Hello 🪐\nNext line."


def test_pdf_has_physical_pages_and_scans_are_rejected(tmp_path):
    from reportlab.pdfgen.canvas import Canvas
    from rag_runtime.parsing import parse_file
    from rag_runtime.errors import Problem
    path = tmp_path / "pages.pdf"
    c = Canvas(str(path))
    c.drawString(72,720,"NEBULA-42 means clock offset.")
    c.showPage()
    c.drawString(72,720,"Synchronize the clock.")
    c.save()
    result = parse_file(path,"pdf")
    assert [p["page"] for p in result["segments"]] == [1,2]
    assert "NEBULA-42" in result["text"]
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-corrupt")
    with pytest.raises(Problem):
        parse_file(bad,"pdf")
