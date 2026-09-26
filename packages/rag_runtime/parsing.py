"""Canonical text with physical page / record boundaries and code-point offsets."""
import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path

from .errors import Problem

MAX_FILE = 20 * 1024 * 1024
MAX_CHARS = 2_000_000


def parse_file(path: Path, kind: str) -> dict:
    if path.stat().st_size > MAX_FILE:
        raise Problem("SOURCE_TOO_LARGE", "A source must be at most 20 MiB.")
    raw = path.read_bytes()
    if kind in ("text", "markdown"):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise Problem("INVALID_ENCODING", "Text and Markdown sources must use UTF-8.") from None
        if "\x00" in text:
            raise Problem("UNSUPPORTED_SOURCE", "Binary data is not a text source.")
        segments = [dict(start=0, end=len(text), page=None)]
        parser, revision = "utf8", "1"
    elif kind == "pdf":
        from pypdf import PdfReader
        try:
            pdf = PdfReader(path, strict=True)
            if pdf.is_encrypted:
                raise Problem("ENCRYPTED_PDF", "Upload an unencrypted text-layer PDF.")
            if len(pdf.pages) > 500:
                raise Problem("SOURCE_TOO_LARGE", "A PDF must have at most 500 pages.")
            page_text = [p.extract_text() or "" for p in pdf.pages]
            if not any(t.strip() for t in page_text):
                raise Problem("SCANNED_PDF", "This PDF has no text layer. OCR is not enabled.")
            for page, extracted in zip(pdf.pages, page_text):
                if not extracted.strip() and len(page.images):
                    raise Problem("SCANNED_PDF", "A page contains images without a text layer. OCR is not enabled.")
        except Problem:
            raise
        except Exception:
            raise Problem("INVALID_PDF", "The PDF is damaged or cannot be read.") from None
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        options = PdfPipelineOptions(do_ocr=False, do_table_structure=True, document_timeout=110,
                                     enable_remote_services=False, allow_external_plugins=False)
        try:
            result = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(
                pipeline_options=options)}).convert(path, max_num_pages=500, max_file_size=MAX_FILE)
            if result.status.value != "success":
                raise Problem("PDF_PARSE_FAILED", "PDF conversion did not finish successfully.")
            pages = [result.document.export_to_markdown(page_no=i, image_placeholder="", escape_html=False)
                     for i in range(1, len(page_text) + 1)]
        except Problem:
            raise
        except Exception:
            raise Problem("PDF_PARSE_FAILED", "PDF parsing failed. Check the installed Docling model assets.") from None
        text, segments = "", []
        for i, page in enumerate(pages, 1):
            start = len(text)
            text += page
            segments.append(dict(start=start, end=len(text), page=i))
            text += "\n\n" if i < len(pages) else ""
        parser, revision = "docling", version("docling")
    else:
        raise Problem("UNSUPPORTED_SOURCE", "Supported uploads are UTF-8 text, Markdown and text-layer PDF.")
    if not text.strip():
        raise Problem("EMPTY_SOURCE", "The source contains no readable text.")
    if len(text) > MAX_CHARS:
        raise Problem("SOURCE_TOO_LARGE", "A source must contain at most two million characters.")
    return dict(text=text, segments=segments, sha256=hashlib.sha256(raw).hexdigest(), format=kind,
                parser=parser, parser_revision=revision)


if __name__ == "__main__":
    try:
        print(json.dumps(parse_file(Path(sys.argv[1]), sys.argv[2]), ensure_ascii=False))
    except Problem as exc:
        print(json.dumps({"error": exc.public()}))
        sys.exit(1)
