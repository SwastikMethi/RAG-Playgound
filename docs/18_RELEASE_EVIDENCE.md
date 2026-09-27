# Release evidence map

This maps [document 11](11_ACCEPTANCE_TESTS.md) to checks and inspected output. Actual aggregate results, model identities and external limitations are in [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md). Fixture responses do not verify live models.

| Gates | Evidence |
| --- | --- |
| A01–A03 | `test_runtime.py`: UTF-8/Unicode spans, physical PDF pages, corrupt/encrypted/no-text rejection; API/browser upload |
| A04–A08 | `test_api.py`, `test_hybrid.py`: frozen scoping, revisions, reuse, unready rejection; `test_embeddings.py`: dimension/token caps |
| A09–A12 | Six-lane live report, `test_hybrid.py`, `test_api.py`, browser journeys: independent lanes, exact source inspection, insufficient evidence, feedback/linked reruns |
| R01–R02 | Actual BM25 identifier ranking and zero-overlap filtering in `test_runtime.py` |
| R03–R05 | Real scoped Qdrant in `test_vectors.py`; hand-calculated RRF/ties in `test_runtime.py`; actual weights in `test_reranker.py`; passage-linked rank-change inspector |
| R06–R07 | Parent deduplication/child links and context clipping in `test_runtime.py`; preparation/query in `test_hybrid.py`; live parent/child inspector |
| R08–R11 | Actual SDK build/query/export in `test_pageindex.py`; unknown-node repair, page mapping/caps in `test_tree.py`; live OpenAI indexing/navigation and selected-page inspector |
| R12 | Provider token/dimension prevalidation in `test_embeddings.py` |
| E01–E02 | Parallel wall timing in `test_parallel.py`; independent metrics in `test_hybrid.py`; tree calls/final-generation timing in `test_pageindex.py` and live report |
| E03–E07 | Persisted SSE cursor in `test_api.py`; frontend Unicode/hash/deduplication/gap/replay tests; browser reconnection with no new run; live replay frames/speed/seek |
| E08–E11 | `test_recovery.py`, `test_execution.py`, `test_foundations.py`: pre-start/partial cancellation, subprocess termination, deadlines, lease fencing, coordinator recovery; parallel failure isolation; live cancellation |
| E12–E14 | API idempotency/conflict/no-evidence; `test_provider.py` pre-text retries/post-text failure; recorded wait/attempt metrics |
| S01 | API auth contracts, protected streams/source/artifact/export downloads; standalone HTTP query 401 |
| S02–S03 | Hostile HTML/script/image/JavaScript-link/instruction browser payload: no execution or external fetch; no tool-execution surface; secrets excluded from logs/portable config. This does not claim a model can never follow misleading source prose. |
| S04–S07 | `test_postgres_source.py`: host/relation/column policy, quoted identifiers, read-only role, stable keys, repeatable-read, caps, frozen query after DB mutation and credential removal |
| S08–S09 | `test_deletion.py`: busy guard, confirmation, retry, cascade, scoped vectors; API cross-project reference checks |
| X01–X02 | `test_export.py`: all-adapter private byte scans, snapshot inclusion, lock/source hashes, tamper failure; tree/database exports |
| X03 | Fresh exported environment: locked install, verify, PDF re-ingestion, live CLI/HTTP query; standalone report |
| X04–X06 | Copied-runtime offline replay for all adapters, default live-not-run manifest/UI, actual dense/PageIndex live replay; PageIndex rebuild included |
| X07 | `test_export_safety.py`: runtime symlink/traversal rejection; export entry allowlist and no-data archive inspection |
| U01–U04 | Inspected sources/compare/history/export/setup; six lanes at required viewports, content wrap/local scrolling and source access |
| U05–U07 | All 35 saved live steps: purpose/input/action/result/duration, parallel branches, passage identity/ranks, child-to-parent links, PDF section/page selection |
| U08–U10 | Reducer/timeline tests and saved-run review: previous/next/seek/final, 4× speed, compressed waits, explicit Follow live, replay 0/70/140, original measured times |
| U11–U13 | Empty/preparing/waiting/streaming/completed, disconnected recovery, failed/cancelled saved runs, unsupported technique messages; mobile keyboard, reduced motion, 200% CSS zoom; status report screenshots |

## Reproduce

With private local services, installed PDF/reranker assets and dependencies:

```sh
.venv/bin/python -m pytest tests/unit tests/integration -q
npm test
npm run build
npm run test:e2e
.venv/bin/python tools/validate_pack.py
.venv/bin/ruff check apps/api packages workers tests tools
```

The browser suite serves the built frontend; build first. Python/browser tests use separate PostgreSQL databases and vector namespaces. Optional live verification is explicit: `.venv/bin/python tools/verify_live.py --allow-model-calls`. It uses a generated fictional PDF. `node tools/review_saved_run.mjs` replays saved smoke results and records screenshots without new model calls.
