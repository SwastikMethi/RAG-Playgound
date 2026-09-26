# Implementation status

Implementation is in progress on `codex/implement-rag-playground`. The approved scope is [the execution plan](docs/14_EXECUTION_PLAN.md); [document 11](docs/11_ACCEPTANCE_TESTS.md) is the release gate.

| Milestone | State | Evidence |
| --- | --- | --- |
| M0 foundations | Verified foundation | 44 API contracts; four foundation/auth/revision tests; frontend production build |
| M1 BM25 slice | Verified functional slice | 12 Python checks, reducer check, production build and browser upload → prepare → answer → citation → replay journey pass |
| M2 dense/hybrid/rerank | Verified functional adapters | 17 Python checks pass, including real Qdrant isolation, cross-encoder inference, parallel wall timing, preparation reuse and failure isolation |
| M3 traces/recovery | Pending | |
| M4 hierarchy/PageIndex | Pending | |
| M5 PostgreSQL source | Pending | |
| M6 export | Pending | |
| M7 product completion | Pending | |
| M8 release verification | Pending | |

## Verified before implementation

All 16 original implementation documents, six configuration examples, 45 trace examples and 40 API operations passed pack/schema checks using the supported OpenAPI validator entry point in a temporary in-memory probe. The original validator fails with openapi-spec-validator 0.9.0 because its deprecated shortcut ignores the supplied reference base URI.

## Decisions

- The user selected an owner-configured OpenAI-compatible endpoint. Live credentials/models are not yet configured for this application.
- This was a new directory with no Git history or unrelated application changes; implementation uses a dedicated initial branch in place.
- PostgreSQL owns jobs and event recovery; no Redis or extra broker.
- Fixture preview is explicit and separate from live projects.

## Verification still required

Full application checks, rendered UI evidence, actual reranker weights, and PageIndex indexing remain unverified until recorded below. No real model-provider calls have been made. PageIndex 0.2.19 public local indexing/tree/page APIs were inspected successfully; this is not a live indexing result.

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
