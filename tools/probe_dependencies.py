"""Probe the pinned public SDK. Live indexing is an explicit opt-in owner operation."""

import argparse
import asyncio
import inspect
import json
import tempfile
from pathlib import Path
from importlib.metadata import version

from rag_runtime.pageindex_adapter import SDK_VERSION, unavailable_reason


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--profile")
    args = parser.parse_args()
    reason = unavailable_reason()
    if reason:
        parser.error(reason)
    from pageindex import PageIndexClient

    for method, fields in [
        ("submit_document", ("file_path", "wait")),
        ("get_tree", ("doc_id", "node_summary", "include_text")),
        ("get_page_content", ("doc_id", "pages")),
    ]:
        signature = inspect.signature(getattr(PageIndexClient, method))
        assert all(field in signature.parameters for field in fields), (method, signature)
    report = dict(
        pageindex=version("pageindex"),
        pinned=SDK_VERSION,
        public_interfaces="passed",
        live_indexing="not_requested",
    )
    if args.live:
        if not args.pdf or not args.profile:
            parser.error("--live requires --pdf and --profile")
        from app.settings import Settings
        from rag_runtime.providers import load_profiles, Gateway
        from rag_runtime.parsing import parse_file
        from rag_runtime.pageindex_build import build_document

        settings = Settings()
        profile = load_profiles(settings).get(args.profile)
        if not profile or profile.kind != "openai" or "tree_indexing" not in profile.operations:
            parser.error("Select a live owner-configured tree_indexing profile")
        source = parse_file(args.pdf, "pdf")
        source.update(source_id="compatibility-probe", name="compatibility-probe.pdf")
        with tempfile.TemporaryDirectory() as root:
            result = asyncio.run(build_document(args.pdf.resolve(), source, profile, Gateway(), root=root))
        report.update(
            live_indexing="passed",
            root_nodes=len(result["nodes"]),
            pages=len(result["page_hashes"]),
            model_calls=len(result["recordings"]),
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
