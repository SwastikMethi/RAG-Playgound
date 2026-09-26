# Decisions and source notes

Specification date 26 September 2026. This pack translates the user's clarified playground concept into a bounded implementable release. Product limits, timings, architecture and delivery choices below are proposed engineering decisions, not externally benchmarked claims.

## Decisions

| ID | Decision | Reason and consequence |
| --- | --- | --- |
| D01 | Manual comparison is the core | Users inspect answers, evidence and time without a mandatory evaluation dataset |
| D02 | v1 is single-owner and self-hosted | Keep data access and deployment bounded; hosted tenancy is separate work |
| D03 | Six adapters are required across milestones | Cover basic search, hybrid/reranking, hierarchy and PageIndex without unlimited initial scope |
| D04 | Visualize real events | Enable explanation, debugging and replay without fabricated internals |
| D05 | Shared final generation settings enforced within each run | Make retrieval differences easier to interpret and keep configuration changes visible |
| D06 | Prepare indexes separately | Prevent setup work from distorting per-question timers |
| D07 | PostgreSQL stores jobs and events | Durable recovery with fewer services at playground scale |
| D08 | Exact dense search is the initial default | Bounded corpora permit a simple baseline; HNSW is an explicit advanced option |
| D09 | PostgreSQL input means text snapshots | Avoid conflating row retrieval with analytical SQL or live record lookup |
| D10 | Export packages the same runtime | Reduce divergence between the observed run and user's implementation |
| D11 | PageIndex uses an explicit bounded controller | Observable tree/page operations and common answering, with honest implementation labeling |
| D12 | Provider and dependency versions are resolved during implementation | Avoid prescribing obsolete or incompatible package/API combinations |
| D13 | Mature, uncluttered design is a release requirement | User explicitly requested deliberate visual quality and the right amount of information; document 13 and U-series gates make it actionable |
| D14 | Step-level explanation is a projection of actual trace events | Keep simulations crisp without fabricating operations, changing timing or adding a separate execution engine |

The working product name is RAG Playground. It can be renamed without changing contracts. English is the initial UI language. Source-language quality depends on the selected embedding, reranking and generation models; the product must not imply universal multilingual support.

The recommended initial local reranker is cross-encoder/ms-marco-MiniLM-L6-v2. Verify and pin its model revision during implementation; its model card identifies it as an English cross-encoder. The application must display the selected model and scoring window.

## Compatibility checks that must be completed

These are executable engineering tasks, not unresolved product decisions:

1. Install compatible stable dependency releases and record lockfiles.
2. Verify PageIndex local tree/page APIs on a small text PDF and normalize the returned node structure.
3. Validate embedding and answer-provider context limits, streaming format, timeout behavior and usage reporting.
4. Verify the selected reranker token limit, revision, runtime backend and licensing notice.
5. Confirm parser page/offset provenance and unsupported PDF handling.
6. Prove exported-runtime installation and replay in an isolated environment.

## Primary references

References support the existence or behavior of external building blocks. The application-specific algorithms and limits in this pack remain explicit design choices.

| Ref | Primary source | Relevance |
| --- | --- | --- |
| S01 | [RAGBuilder repository](https://github.com/KruxAI/ragbuilder) | Prior art for configurable retrieval pipelines and optimization |
| S02 | [RAGBuilder UI documentation](https://github.com/KruxAI/ragbuilder-readme) | Prior art for per-configuration code snippets |
| S03 | [AutoRAG legacy optimizer](https://github.com/Marker-Inc-Korea/AutoRAG/blob/main/legacy/README.md) | Existing optimization category; distinct from this manual playground scope |
| S04 | [Rank BM25](https://github.com/dorianbrown/rank_bm25) | BM25 implementation and caller-owned tokenization |
| S05 | [Qdrant hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/) | Multi-stage retrieval and reciprocal rank fusion |
| S06 | [Qdrant filtering](https://qdrant.tech/documentation/search/filtering/) | Scoped vector queries and metadata filtering |
| S07 | [ParentDocumentRetriever reference](https://reference.langchain.com/python/langchain-classic/retrievers/parent_document_retriever/ParentDocumentRetriever) | Retrieving children and returning larger parents |
| S08 | [PageIndex repository](https://github.com/VectifyAI/PageIndex) | Actual PageIndex indexing and retrieval project |
| S09 | [PageIndex client configuration](https://docs.pageindex.ai/sdk/client) | Local/cloud and provider configuration boundaries |
| S10 | [PageIndex document processing](https://docs.pageindex.ai/sdk/documents) | Public indexing, tree and page-content interfaces |
| S11 | [PageIndex tree-search tutorials](https://docs.pageindex.ai/tutorials/tree-search) | Tree-retrieval integration reference |
| S12 | [Docling converter](https://docling-project.github.io/docling/reference/document_converter/) | Document conversion boundary and provenance implementation starting point |
| S13 | [Cross-encoder model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) | Recommended initial reranker and model limitations |
| S14 | [React Flow documentation](https://reactflow.dev/learn) | Interactive node/edge visualization |
| S15 | [MDN server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) | SSE event format, IDs and reconnection concepts |
| S16 | [FastAPI streaming responses](https://fastapi.tiangolo.com/advanced/custom-response/) | HTTP streaming implementation |
| S17 | [PostgreSQL SELECT](https://www.postgresql.org/docs/current/sql-select.html) | SKIP LOCKED worker claim mechanism and SQL semantics |
| S18 | [Microsoft GraphRAG](https://microsoft.github.io/graphrag/) | Later graph-retrieval extension |
| S19 | [RAPTOR paper](https://arxiv.org/abs/2401.18059) | Later summary-tree extension |
| S20 | [Anthropic contextual retrieval](https://www.anthropic.com/engineering/contextual-retrieval) | Later context-enriched indexing extension |

Some source APIs and documentation can change. Pin tested versions and retain an integration probe. Do not infer a vendor's benchmark performance for this application's custom controller or for a user's data.

## Research interpretation

Existing tools already cover retrieval experimentation, optimization and code output. This product focuses its implementation on immediate question-by-question comparison, visible evidence movement and portable replay. No claim is made that these features are unprecedented or that the architecture guarantees commercial demand.

The success criterion is the user journey and honest observability. Optional automated evaluation can be added later without changing the meaning of the current comparison results.
