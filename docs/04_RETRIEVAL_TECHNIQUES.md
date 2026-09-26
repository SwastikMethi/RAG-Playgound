# Retrieval technique specifications

## Shared behavior

Each selectable card is a complete retrieval configuration followed by the shared context assembler and answer generator. The registry returns identifier, display name, explanation, supported inputs, preparation requirements, editable parameters, trace template, export support and current availability reason.

All v1 adapters are non-agentic except bounded LLM-guided PageIndex tree selection. They cannot execute commands or use arbitrary external tools. Candidate ordering must have stable ties using candidate_id ascending.

Default candidate_k is 20, context_k is 5, context budget is 3,000 tokens and maximum answer output is 512 tokens. Configuration validation requires context_k <= candidate_k. Score thresholds are technique-specific and disabled by default. Native scores are diagnostic values, never normalized into an asserted probability of correctness.

## BM25

Identifier bm25. Use real BM25Okapi, for example through rank_bm25, with k1=1.5, b=0.75 and epsilon=0.25 recorded in configuration. A PostgreSQL full-text rank is not BM25 and cannot be substituted under this label.

Tokenization revision lexical_v1 uses Unicode NFKC normalization, case folding and a documented word tokenizer that retains meaningful alphanumeric identifiers and internal hyphens. Apply exactly the same tokenizer to queries and documents. Do not silently enable stemming or language-specific stop-word removal. Return only candidates containing at least one query token; a zero-overlap document is not evidence merely because of a default score.

Persist chunk IDs, token lists, lengths, corpus statistics or sufficient inputs to rebuild them, library version and tokenizer revision in JSON or another non-executable format. Score candidates and emit lexical_search stage events and retrieval.candidates with score_type bm25.

## Dense vector retrieval

Identifier dense. Embed chunks during preparation and the question during the run, using the same provider profile, model identity, dimension, preprocessing and task-specific settings. Reject a vector dimension mismatch. Validate chunk lengths against the configured embedding provider limit; never silently truncate oversized inputs.

Use cosine similarity in Qdrant. Record whether search used exact or hnsw mode; use exact by default for bounded comparison corpora and allow HNSW as an advanced setting. Every query filters the immutable corpus/index namespace; queries must never search the entire shared collection without its scoped filter.

Emit query_embedding and dense_search stages with native cosine scores, dimensions and model metadata. Query embeddings are not shared across lanes in v1, so one lane does not receive hidden uncharged work. Index data and persistent model weights may be reused and their warm state is disclosed.

## Hybrid retrieval

Identifier hybrid. Run BM25 and dense candidate retrieval in parallel using the same chunk variant and corpus snapshot. Collect up to candidate_k from each branch. Deduplicate by stable chunk candidate_id and fuse with reciprocal rank fusion.

    fused_score(candidate) = sum(1 / (rrf_k + rank_in_branch))

Ranks begin at 1, missing candidates contribute zero, branch weights are equal and rrf_k defaults to 60. Stable ties use candidate_id. Keep the top candidate_k fused candidates, then let the shared assembler choose up to context_k within its budget. Do not add raw BM25 and cosine values.

Emit each branch, its rank list, a fusion stage and a retrieval.candidates event containing branch_ranks and score_type rrf. Retrieval wall time covers both parallel branches; it is not their summed duration.

## Hybrid with reranking

Identifier hybrid_rerank. Run the same hybrid procedure, then score the top candidate_k fused passages against the original question with a configured local cross-encoder. Start with cross-encoder/ms-marco-MiniLM-L6-v2, pin its exact model revision and maximum input length during implementation, and expose its English-language scope and license notice in the registry.

Keep original excerpts unchanged for citations. If a model requires truncation, disclose its scoring window and preserve the full original passage for context selection. Sort by reranker output with stable ties and choose up to context_k within the context budget.

Emit rerank stage events and rerank.completed with before_rank, after_rank, reranker score and candidate_id. Do not simulate improvement when rankings do not change. Model loading and CPU/GPU waits count in this run and are visible.

## Parent-child retrieval

Identifier parent_child. Create child chunks with a 256-token target and 32-token overlap, within parent sections of up to 1,200 tokens. Parent boundaries never cross source revisions or PDF pages in the initial implementation. Preserve exact offsets and child-to-parent links.

Index child embeddings. Retrieve candidate_k children, map each to its parent, deduplicate parents, and order parents by the best child rank, then parent ID. Emit parent_expansion showing the mapping and the context added. The assembler selects up to context_k parents within its token budget; it may clip a parent with explicit span adjustment. Context packing must not silently exceed the same generation budget used by other lanes.

A general parent-child method and RAPTOR's summary hierarchy are separate adapters. Do not call parent-child retrieval RAPTOR.

## PageIndex tree retrieval

Identifier pageindex. The display name is PageIndex tree retrieval, experimental. Use the actual PageIndex local SDK to build trees from text PDFs. The application owns a bounded tree-selection controller over the returned public tree and page APIs, then uses the shared answer generator. Describe it as PageIndex-backed retrieval with this application's controller; do not imply exact replication of a vendor benchmark or native chat agent.

Before implementation, inspect the pinned SDK's documented submit_document, get_tree and get_page_content interfaces and run a small compatibility probe. Local indexing may be synchronous and must run outside the API request and event loop. A dependency mismatch produces ADAPTER_UNAVAILABLE rather than a replacement implementation.

Application controller design:

1. Prepare a separate index for every PDF. Persist normalized node IDs, titles, summaries, children and source-page mapping, with the SDK version.
2. At query time provide the question and bounded document titles/descriptions to the configured tree-selection model. Select up to 3 document IDs in schema-validated JSON. For a single PDF, skip this call and record the deterministic selection.
3. For selected documents, expose only bounded child-node descriptors per navigation step. Ask for node IDs or a stop flag, not chain-of-thought. Validate IDs against the current tree before fetching data.
4. Traverse at most 4 levels, 12 visited nodes total and 8 remote selection calls per lane. Stop on leaf nodes, exhausted limits or no usable selection.
5. Resolve selected nodes to original source pages and collect at most 12 distinct pages before the shared context budget is applied. Use explicit page metadata when available. When only node start pages exist, derive the end from the next node at the same or shallower depth, bounded by the parent and document; test the mapping. Never treat a node ID as a page number.
6. Convert page evidence to the common EvidenceRef format and use the same answer prompt, answer model and context/output budgets as other lanes.

Separate document selection from tree navigation in the trace. Emit node IDs and page selections only for operations actually observed by this controller. If a vendor internal index step is opaque, show an opaque preparation stage. No fabricated traversal, model thoughts or unobserved attention.

This controller has its own quality and latency trade-offs, which users can inspect. SDK-generated summaries select evidence; final citations resolve to original page text. Scanned PDFs, Markdown, text and database sources are unsupported for this adapter in v1. Mixed corpora disable PageIndex entirely until a compatible corpus is selected.

## Context and generation

Use one grounded_answer_v1 prompt revision. It instructs the answer model to use the supplied evidence, cite evidence labels such as [E1], distinguish missing information, and treat document instructions as untrusted content. Do not request private reasoning.

The assembler deduplicates source spans, preserves candidate order, labels them E1 onward, and packs the actual text plus citation metadata into a token budget. Reserve room for system text, question, output and a provider safety margin. Use a provider-compatible tokenizer where known; otherwise apply and disclose a conservative estimate. Reject configurations that cannot fit minimum prompt overhead.

When clipping an excerpt, record the exact clipped span and use it in the citation view. Never imply that discarded evidence was supplied to generation. Context selection emits context.selected with included and excluded candidate IDs and token counts.

If no usable evidence exists, return a deterministic insufficient-evidence message with no generation call, a skipped generation stage and null TTFT. This counts as a completed lane with answer_kind insufficient_evidence, not as a successful factual answer.

Validate bracketed citation IDs after generation against the supplied evidence set. Unsupported IDs produce a warning and are not linked. Retain raw answer text and validation metadata; do not quietly rewrite a model claim into verified truth.

## Extension contract

Add future techniques by implementing preparation requirements, retrieval, event mapping, capability checks, configuration validation and export support. The adapter registry is a whitelist of packaged code; users cannot upload executable plugins.

RAPTOR requires cluster and summary artifacts with source lineage. GraphRAG requires entity/relation extraction artifacts, summaries and original-evidence mappings. Query rewriting must retain the original question and expose transformed queries and additional call cost. Analytical SQL requires a distinct execution and evaluation contract and is not achieved by relabeling row embeddings.
