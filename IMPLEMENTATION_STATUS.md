# Implementation status

Implementation is in progress on `codex/implement-rag-playground`. The approved scope is [the execution plan](docs/14_EXECUTION_PLAN.md); [document 11](docs/11_ACCEPTANCE_TESTS.md) is the release gate.

| Milestone | State | Evidence |
| --- | --- | --- |
| M0 foundations | Verified foundation | 44 API contracts; four foundation/auth/revision tests; frontend production build |
| M1 BM25 slice | Verified functional slice | 12 Python checks, reducer check, production build and browser upload → prepare → answer → citation → replay journey pass |
| M2 dense/hybrid/rerank | Verified functional adapters | 17 Python checks pass, including real Qdrant isolation, cross-encoder inference, parallel wall timing, preparation reuse and failure isolation |
| M3 traces/recovery | Verified event and recovery path | 25 Python checks, 3 frontend checks; fixed workflow graphs and step inspector; persisted replay, Unicode/citation integrity, cancellation, deadlines and worker fencing |
| M4 hierarchy/PageIndex | Implemented; live models pending | Real parent-child vector path; PageIndex 0.2.19 PDF indexing, tree/page APIs, bounded selection and end-to-end worker tested with synthetic model boundaries |
| M5 PostgreSQL source | Implemented and integration checked | Encrypted credentials, exact host/relation/column policy, read-only repeatable-read snapshots, stable keys, preview, refresh and row evidence; three real PostgreSQL integration tests |
| M6 export | Implemented and replay checked | Shared runtime/preparation, all six adapter exports, PostgreSQL snapshots, no-data privacy, copied-runtime replay, standalone CLI/API, protected ZIP download |
| M7 product completion | Pending | |
| M8 release verification | Pending | |

## Verified before implementation

All 16 original implementation documents, six configuration examples, 45 trace examples and 40 API operations passed pack/schema checks using the supported OpenAPI validator entry point in a temporary in-memory probe. The original validator fails with openapi-spec-validator 0.9.0 because its deprecated shortcut ignores the supplied reference base URI.

## Decisions

- The user selected the standard OpenAI API endpoint. Server profiles use GPT-4.1 mini (2025-04-14 snapshot) and text-embedding-3-small (1,536 dimensions). The supplied OPENAI_API_KEY is stored only in the ignored local .env; live calls remain to be verified.
- This was a new directory with no Git history or unrelated application changes; implementation uses a dedicated initial branch in place.
- PostgreSQL owns jobs and event recovery; no Redis or extra broker.
- Fixture preview is explicit and separate from live projects.

## Verification still required

Release-wide checks and full rendered state coverage remain pending. Actual reranker weights and inference are verified below; live PageIndex indexing is not yet verified. No real model-provider calls have been made. PageIndex 0.2.19 public local indexing/tree/page APIs were inspected successfully; this is not a live indexing result.

## Recorded checks

- `.venv/bin/python -m pytest tests/unit/test_contracts.py tests/integration/test_foundations.py tests/integration/test_api.py -q`: 4 passed, using dedicated PostgreSQL test database.
- `.venv/bin/python -m pytest tests/unit/test_runtime.py -q`: 6 passed, real BM25, tokenization and Docling PDF conversion. Model asset initialization took roughly two minutes.
- `npm run generate:types` and `npm run build`: passed. Host Node 25 was used; supported Node 22 container validation remains pending.
- M1 `.venv/bin/python -m pytest tests/unit tests/integration -q`: 12 passed. The evidence-list response was subsequently corrected to the authoritative contract and its journey test passed again.
- M1 `npm test`: one reducer check passed for Unicode offsets, duplicate frames, sequence gaps and replay reconstruction.
- M1 `npm run test:e2e`: one complete browser journey passed against the real API/worker/PostgreSQL, with an explicitly synthetic model provider.
- Inspected `test-results/bm25-desktop.png` (1440px) and `test-results/bm25-mobile.png` (390px). Source and answer text are readable and there is no mobile horizontal overflow. This is provisional visual evidence: vertical density, mobile workspace controls, complete workflows, 1024px, keyboard and reduced-motion gates remain for M7/M8.
- M2 actual cross-encoder inference passed using `cross-encoder/ms-marco-MiniLM-L6-v2@233902d25c440f23af6f7d6e94d2946bac0bee0a`, CPU, safetensors, offline loading. Public weights were downloaded explicitly; no private source data was sent for this setup.
- Qdrant client and server are both pinned to 1.17.0 after a compatibility warning on the initially resolved client. Scoped read/delete checks pass without the warning.

- M4 PageIndex actual SDK indexing and original-page mapping passed against a local synthetic summary provider. Its internal retry ladder cannot bypass the application’s two-attempt limit; cancellation kills the owned indexing process group and removes its temporary store. This is a real SDK compatibility check, not live model verification.
- Model settings were checked against the [OpenAI model reference](https://developers.openai.com/api/docs/models/gpt-4.1-mini) and [embedding guide](https://developers.openai.com/api/docs/guides/embeddings). The PageIndex adapter follows its [public document APIs](https://docs.pageindex.ai/sdk/documents).

## PostgreSQL snapshot verification

Three real PostgreSQL tests pass with a dedicated column-scoped read-only role: hostile quoted identifiers, encrypted credentials, approved columns, cross-project isolation, duplicate/null key rejection, write-role rejection, row/byte caps, repeatable-read isolation and statement deadlines. Capture refresh creates a distinct source; old answers use frozen row text after database mutation and connection deletion. Two execution/network checks also pass, including metadata-address rejection. The connection UI and row inspector compile; rendered connector review remains in M7. Setup policy is documented in [operating instructions](docs/17_RUNNING_THE_APPLICATION.md).

## Export verification

The full application suite passes 41 tests (98.90 s), including six export integration tests, actual PageIndex SDK export replay and captured PostgreSQL row export. Offline replay runs the copied runtime in an owned subprocess and compares evidence IDs/order, source mapping, exact generation-context requests and answer assembly. Qdrant local exact replay uses stored embeddings; model, reranker and tree-selection responses are recorded boundaries. This does not claim remote HNSW or fresh provider performance.

No-data archive scans exclude private fixture text, original file names, questions, answers and application tokens. Included-data ingestion rejects changed source hashes. A corrupted boundary recording fails the export and removes its download URL. The generated lock resolves independently and installs 165 dependencies in an isolated virtual environment; standalone ingest, query and API checks use the labeled synthetic model provider. Browser upload → prepare → answer → evidence → workflow → replay → export/download passes (11.0 s). The production frontend build passes. Inspected `test-results/export-desktop.png`; design density and checkbox alignment remain for M7. No public deployment was performed.
