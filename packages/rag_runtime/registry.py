"""Six concrete adapters and server-resolved effective defaults."""

from importlib.metadata import version, PackageNotFoundError

from .contracts import digest, validate
from .errors import Problem
from .reranker import unavailable_reason as reranker_unavailable

TECHNIQUES = {
    "bm25": ("Keyword · BM25", "Ranks passages by matching words and their rarity in your corpus."),
    "dense": ("Semantic · Dense", "Embeds the question and finds passages with similar vectors."),
    "hybrid": ("Hybrid", "Runs keyword and semantic search together, then combines their ranks."),
    "hybrid_rerank": (
        "Hybrid + reranking",
        "Scores hybrid candidates against the question with a local cross-encoder.",
    ),
    "parent_child": ("Parent–child", "Finds small passages, then supplies their larger parent sections."),
    "pageindex": ("PageIndex", "Selects relevant PDF sections through a bounded document tree traversal."),
}


def defaults(technique: str, profiles: dict, reranker_revision: str = "") -> dict | None:
    def profile(operation):
        return next(
            (
                p
                for p in profiles.values()
                if operation in p.operations and (operation != "embedding" or p.dimensions)
            ),
            None,
        )

    gen, emb, index, selection = [
        profile(op) for op in ("generation", "embedding", "tree_indexing", "tree_selection")
    ]
    vector = technique in {"dense", "hybrid", "hybrid_rerank", "parent_child"}
    tree = technique == "pageindex"
    if not gen or (vector and not emb) or (tree and (not index or not selection)):
        return None
    child = technique == "parent_child"
    lexical = technique in {"bm25", "hybrid", "hybrid_rerank"}
    return dict(
        schema_version="1.0.0",
        technique=technique,
        chunking=None
        if tree
        else dict(
            strategy="fixed_tokens",
            size_tokens=256 if child else 512,
            overlap_tokens=32 if child else 64,
            tokenizer="cl100k_base",
            tokenizer_revision=version("tiktoken"),
        ),
        embedding=dict(
            profile_id=emb.id, model=emb.model, dimensions=emb.dimensions, document_prefix="", query_prefix=""
        )
        if vector
        else None,
        search=dict(
            candidate_k=20,
            context_k=5,
            bm25=dict(k1=1.5, b=0.75, epsilon=0.25, tokenizer_revision="lexical_v1") if lexical else None,
            dense=dict(metric="cosine", mode="exact", hnsw_ef=None, min_score=None) if vector else None,
            rrf=dict(k=60, weights="equal") if lexical and vector else None,
        ),
        reranker=dict(
            model="cross-encoder/ms-marco-MiniLM-L6-v2",
            model_revision=reranker_revision or None,
            max_input_tokens=512,
            device="cpu",
        )
        if technique == "hybrid_rerank"
        else None,
        parent=dict(max_parent_tokens=1200, boundary="source_and_page") if child else None,
        tree=dict(
            index_profile_id=index.id,
            index_model=index.model,
            selection_profile_id=selection.id,
            selection_model=selection.model,
            sdk_version=installed_version("pageindex"),
            max_documents=3,
            max_depth=4,
            max_nodes=12,
            max_calls=8,
            max_pages=12,
        )
        if tree
        else None,
        generation=dict(
            profile_id=gen.id,
            model=gen.model,
            temperature=0,
            max_output_tokens=512,
            context_budget_tokens=3000,
            prompt_id="grounded_answer_v1",
            seed=None,
        ),
        limits=dict(lane_timeout_ms=90000),
    )


def resolve_profile(profiles: dict, profile_id: str, model: str, operation: str):
    p = profiles.get(profile_id)
    if not p or p.model != model or operation not in p.operations:
        raise Problem(
            "PROFILE_CHANGED",
            "The selected model profile is unavailable or has changed. Save a new revision.",
            409,
        )
    if p.unavailable_reason:
        raise Problem("MISSING_CREDENTIALS", p.unavailable_reason, 409)
    return p


def check_config(config: dict, profiles: dict, require_available=True):
    validate(config)
    fields = [(config["generation"], "generation")]
    if config["embedding"]:
        fields.append((config["embedding"], "embedding"))
    if config["tree"]:
        t = config["tree"]
        fields += [
            (dict(profile_id=t["index_profile_id"], model=t["index_model"]), "tree_indexing"),
            (dict(profile_id=t["selection_profile_id"], model=t["selection_model"]), "tree_selection"),
        ]
    for field, operation in fields:
        p = profiles.get(field["profile_id"])
        if not p or p.model != field["model"] or operation not in p.operations:
            raise Problem("PROFILE_CHANGED", "Select an available server-managed model profile.", 409)
        if require_available:
            resolve_profile(profiles, p.id, field["model"], operation)
        if operation == "embedding" and field["dimensions"] != p.dimensions:
            raise Problem("VALIDATION_ERROR", "Embedding dimensions must match the configured model profile.")
        if operation == "generation":
            if field["max_output_tokens"] > (p.max_output_tokens or 0):
                raise Problem("VALIDATION_ERROR", "Output limit exceeds this model profile's capacity.")
            if field["seed"] is not None and not p.supports_seed:
                raise Problem("UNSUPPORTED_PARAMETER", "This profile does not support a seed.")
            if field["temperature"] != 0 and not p.supports_temperature:
                raise Problem("UNSUPPORTED_PARAMETER", "This profile does not support temperature.")
    if config["chunking"]:
        c = config["chunking"]
        if c["tokenizer"] != "cl100k_base" or c["tokenizer_revision"] != version("tiktoken"):
            raise Problem("UNSUPPORTED_TOKENIZER", "Choose the installed cl100k_base tokenizer revision.")
    if config["reranker"]:
        reason = reranker_unavailable(config["reranker"])
        if reason and require_available:
            raise Problem("MODEL_NOT_READY", reason, 409)
    if config["tree"]:
        from .pageindex_adapter import unavailable_reason, SDK_VERSION

        reason = unavailable_reason()
        if require_available and reason:
            raise Problem("ADAPTER_UNAVAILABLE", reason, 409)
        if config["tree"]["sdk_version"] != SDK_VERSION:
            raise Problem(
                "ADAPTER_UNAVAILABLE", "Select a configuration using the tested PageIndex SDK revision.", 409
            )


def installed_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def capabilities(profiles, settings):
    result = []
    for name, (label, description) in TECHNIQUES.items():
        config = defaults(name, profiles, settings.reranker_revision)
        reason = None
        if config is None:
            reason = "Configure the required generation, embedding or tree model profiles on the server."
        else:
            try:
                check_config(config, profiles)
            except Problem as exc:
                reason = exc.message
        result.append(
            dict(
                technique=name,
                display_name=label,
                description=description,
                available=reason is None,
                unavailable_reason=reason,
                supported_source_kinds=["pdf"]
                if name == "pageindex"
                else ["pdf", "markdown", "text", "postgres"],
                export_supported=True,
                default_config=config,
                requirements=(
                    ["Text-layer PDF only; at most 10 documents."]
                    if name == "pageindex"
                    else ["English cross-encoder; Apache-2.0 license; 512-token scoring window."]
                    if name == "hybrid_rerank"
                    else []
                ),
            )
        )
    return dict(items=result, mode=settings.mode)


def preparation_identity(config: dict, corpus_fingerprint: str, profiles: dict) -> str:
    emb, tree = config["embedding"], config["tree"]
    # Query budgets, generation and local reranking never invalidate stored document vectors.
    return digest(
        dict(
            corpus=corpus_fingerprint,
            runtime="0.1.0",
            chunking=config["chunking"],
            parent=config["parent"],
            embedding=emb,
            embedding_profile=profiles[emb["profile_id"]].fingerprint() if emb else None,
            tree_index=dict(
                model=tree["index_model"],
                profile=profiles[tree["index_profile_id"]].fingerprint(),
                sdk=tree["sdk_version"],
            )
            if tree
            else None,
        )
    )
