"""Shared preparation for the playground worker and portable application."""

from importlib.metadata import version
from collections.abc import Callable
from .chunking import chunk_source, parent_child_chunks
from .errors import Problem


async def prepare_sources(
    sources, config, scope, profiles, gateway, *, raw_paths=None, root=None,
    before_embedding: Callable[[int], None] | None = None,
):
    chunks, parents = [], []
    for source in sources:
        if config["tree"]:
            continue
        if config["parent"]:
            children, expanded = parent_child_chunks(
                source, config["chunking"], config["parent"]["max_parent_tokens"]
            )
            chunks.extend(children)
            parents.extend(expanded)
        else:
            chunks.extend(chunk_source(source, config["chunking"]))
    if (not chunks and not config["tree"]) or len(chunks) > 10_000:
        raise Problem("CHUNK_LIMIT", "Preparation requires 1–10,000 chunks.")
    prepared = dict(
        chunks=chunks,
        parents=parents,
        scope=scope,
        format_version="1",
        recordings=[],
        versions=dict(bm25=version("rank-bm25"), lexical="lexical_v1", tokenizer=version("tiktoken")),
    )
    if config["tree"]:
        from .pageindex_build import build_document

        documents = []
        for source in sources:
            document = await build_document(
                raw_paths[source["source_id"]],
                source,
                profiles[config["tree"]["index_profile_id"]],
                gateway,
                root=root,
            )
            prepared["recordings"].extend(document.pop("recordings"))
            documents.append(document)
        prepared.update(
            documents=documents,
            preprocessing="PageIndex SDK builds the tree from the original PDF; final evidence uses canonical original-page extraction.",
        )
        prepared["versions"]["pageindex"] = config["tree"]["sdk_version"]
    if config["embedding"]:
        if before_embedding:
            before_embedding(len(chunks))
        emb = config["embedding"]
        vector = await gateway.embed(
            profiles[emb["profile_id"]], [emb["document_prefix"] + c["excerpt"] for c in chunks]
        )
        prepared["recordings"].append(vector["recording"])
        prepared.update(vectors=vector["vectors"], preparation_usage=vector["usage"])
    return prepared
