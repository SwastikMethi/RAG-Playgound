"""Explicit owner operation: download public local-model assets without sending source content."""

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--reranker", action="store_true")
parser.add_argument("--pdf", action="store_true")
args = parser.parse_args()
if not args.reranker and not args.pdf:
    parser.error("Choose --reranker and/or --pdf")
if args.reranker:
    from huggingface_hub import snapshot_download
    from rag_runtime.reranker import MODEL, REVISION

    snapshot_download(
        MODEL, revision=REVISION, allow_patterns=["*.json", "*.txt", "*.safetensors", "README.md"]
    )
    print(f"Ready: {MODEL}@{REVISION}")
if args.pdf:
    from docling.utils.model_downloader import download_models

    download_models()
    print("Ready: Docling parser assets")
