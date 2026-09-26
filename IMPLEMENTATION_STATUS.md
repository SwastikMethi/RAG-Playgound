# Implementation status

Implementation is in progress on `codex/implement-rag-playground`. The approved scope is [the execution plan](docs/14_EXECUTION_PLAN.md); [document 11](docs/11_ACCEPTANCE_TESTS.md) is the release gate.

| Milestone | State | Evidence |
| --- | --- | --- |
| M0 foundations | In progress | Pack reviewed; validator compatibility bug reproduced; Docker available |
| M1 BM25 slice | Pending | |
| M2 dense/hybrid/rerank | Pending | |
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

Application checks, rendered UI evidence, actual reranker weights, and PageIndex indexing remain unverified until recorded below. No real model-provider calls have been made.
