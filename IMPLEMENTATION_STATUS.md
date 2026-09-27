# Implementation status

M0–M8 implementation, release checks and independent whole-branch review are complete on `codex/implement-rag-playground`. Scope: [execution plan](docs/14_EXECUTION_PLAN.md). Release gate: [document 11](docs/11_ACCEPTANCE_TESTS.md). No public deployment was performed.

## Working application

All six real adapters are implemented: BM25, scoped Qdrant dense retrieval, parallel hybrid RRF, hybrid with a pinned local cross-encoder, parent-child and experimental PageIndex. The application includes file ingestion, frozen PostgreSQL text snapshots, immutable corpus/configuration revisions, preparation reuse, independent streamed answers and citations, measured execution graphs, persisted replay, source inspection, manual feedback, history, reruns, confirmed retryable deletion and standalone export using the same runtime.

Start with [README.md](README.md) or [operating instructions](docs/17_RUNNING_THE_APPLICATION.md). After setup, use `./start.sh` and `./stop.sh` to manage the API, worker and local storage services. Local URL: `http://127.0.0.1:8780`; the workspace opens directly without a login or application token. Configure `OPENAI_API_KEY` in `.env`, never in `.env.example`. Private credentials already supplied on this machine were kept out of Git.

## Local start and stop scripts — 27 September 2026

Added executable `start.sh` and `stop.sh` with shared lifecycle logic in `tools/local_app.py`. Startup waits for Docker storage, applies migrations, builds the frontend and detaches the API/worker with private logs and process records. It checks API readiness and worker initialization before reporting success. Repeated starts reuse the existing pair; failed startup cleans up the processes it launched. Stop validates process identity, stops owned subprocesses and stops PostgreSQL/Qdrant without deleting volumes. No dependencies were added. Setup and troubleshooting instructions now use these scripts.

Verified real start → repeated start → stop → repeated stop → restart, a successful homepage response and readiness `ok`. The existing 31 source records remained present after restart. The lifecycle regression uses real subprocesses and HTTP to check duplicate prevention, stale PID safety and failed-start cleanup while isolating Docker/build commands. The final Python suite passed: 53 tests, four dependency deprecation warnings, 126.58 seconds. Shell syntax, Ruff, production build and pack validation passed. No screens changed and no live provider calls were needed. Existing owner edits to `config/profiles.yaml` were preserved.

## Fifty-source corpus limit — 27 September 2026

The reported `source_ids` error came from the 20-source contract limit: the project had 30 ready sources and the upload flow selected new files without checking that limit. The owner approved raising the limit to 50. Updated corpus requests/responses, per-source parser provenance and export source hashes together. The source panel now displays the selected count against 50, explains how many sources to deselect when oversized and blocks invalid submission. Direct API callers receive an actionable limit/count error without exposing source IDs. Existing byte/page/text/chunk limits and PageIndex's separate 10-PDF compatibility limit remain in effect.

Verified a real 50-source upload → ingestion → corpus → BM25 preparation → answer → offline export flow with all source IDs retained. The browser regression uploads 51 files, verifies the warning/disabled action, deselects one and saves all 50. Full checks: 52 Python tests passed (four dependency deprecation warnings, 134.32 s), five frontend tests, three browser journeys (48.5 s), production build, Ruff and pack validation. A final targeted browser check with screenshots also passed (16.2 s). Inspected 1440×900 and 390×844 warning/count/button states; evidence is under `.data/release/source-limit/`. No live model calls were made for this fix.

Restarted the API and worker after confirming there were no queued/running local jobs; readiness returned `ok`. Existing uploads were retained. Concurrent owner edits to `config/profiles.yaml` were preserved and excluded from this change.

## Application token removal — 27 September 2026

At the owner's request, removed the login/lock controls, browser token storage and request headers, API bearer checks, required token setting and token generation. Removed the obsolete setting from the local `.env` while preserving provider credentials and the encryption master key. Updated the access contract, generated client types, setup instructions and S01 acceptance gate. The playground remains bound to loopback with same-origin checks, CSP, scoped resource lookups and request limits. The separately exported standalone query service retains its own `RAG_QUERY_TOKEN`.

The API and browser regressions first failed at the original token gate, then passed. Verification after removal: 50 Python tests passed (four dependency deprecation warnings, 108.49 s), five frontend tests, two browser journeys (33.1 s), production build, Ruff and pack validation. Browser journeys exercise upload/preparation, SSE/reconnect, source/export downloads and PostgreSQL capture without Authorization headers. Inspected desktop/mobile screenshots at 1440×900 and 390×844: `.data/release/no-token/bm25-desktop.png` and `bm25-mobile.png`. Restarted the local API; readiness returns `ok` without credentials. Backend log: `.data/release/no-token/pytest.log`.

The initial release evidence below remains historical; no new billable OpenAI calls or Docker rebuild were needed for this access change.

## Checks actually run — 27 September 2026

| Check | Result |
| --- | --- |
| Python unit/integration | Final post-review suite: 50 passed, four dependency deprecation warnings, 182.88 seconds |
| Frontend reducer/replay | `npm test`: 5 passed |
| TypeScript/production build | Passed; main chunk warning: 632 kB, 196 kB gzip |
| Browser journeys | 2 passed, 34.2 s including startup; real API/workers/PostgreSQL/Qdrant, explicitly synthetic model responses |
| Pack validator | Passed: 44 API operations, six configurations, 45 example events; separate from application checks |
| Ruff | Passed |
| Linux/Node 22 image | Final image rebuilt successfully after all review fixes; API, Docling, PageIndex and PyTorch `2.11.0+cpu` imports verified |
| Actual reranker | CPU safetensors inference with `cross-encoder/ms-marco-MiniLM-L6-v2@233902d25c440f23af6f7d6e94d2946bac0bee0a` passed |
| Live OpenAI | All six lanes, live embeddings, streamed generation, actual PageIndex SDK indexing/navigation, usage and cancellation passed |
| Export | All six adapters offline-replayed; dense and PageIndex exports additionally live-replayed successfully |
| Fresh standalone package | 165 locked dependencies installed in a separate environment; verify, PDF re-ingestion, live CLI query, HTTP health/auth and live HTTP query passed |

Python tests exercise real BM25, Docling, Qdrant, PostgreSQL, reranker weights and PageIndex SDK interfaces. Deterministic model boundaries make CI reproducible; these are distinct from live results. Tests cover scopes, contracts, immutable revisions, deadlines, cancellation, lease fencing, coordinator recovery, retries, evidence spans, Unicode/hashes, preparation reuse, deletion retries, private exports, encrypted/corrupt/no-text PDF rejection, ZIP traversal and runtime symlink rejection.

The browser journeys cover upload → prepare → answer → citation/download → workflow → replay → export/download → feedback/history/rerun → confirmed deletion. The PostgreSQL journey previews/captures selected columns, inspects frozen row evidence and removes the encrypted connection. Hostile HTML/script/image/JavaScript-link and instruction payloads remain inert and make no external requests. Five interrupted event connections expose recovery; reconnect restores saved output without another run submission. Browser workers have a separate database so they cannot claim Python-test jobs.

## Actual live integration

Authorized calls used `https://api.openai.com/v1`, `gpt-4.1-mini-2025-04-14`, and `text-embedding-3-small` (1,536 dimensions). The source was one generated text-layer PDF explicitly describing a fictional NEBULA-42 clock error. PageIndex 0.2.19 indexed the actual PDF through its SDK. No private business documents were used.

All six answers included E1 source evidence. Answers were inspected against the authored fictional recovery instructions; this does not claim human source verification. The persisted stream contained 20 ordered answer deltas. Completion times: BM25 2.20 s, dense 4.44 s, hybrid 4.55 s, reranking 9.85 s, parent-child 4.44 s, PageIndex 4.56 s. This is a small smoke, not a benchmark. Cancellation reached `cancelled`; upstream usage remained partial/unknown where unreported.

Dense and PageIndex live export replay matched evidence order and answer text on this run; future stochastic answers need not match. Live export replay documents that existing verified indexes were reused. Separately, a fresh standalone dense package rebuilt its index from original PDF bytes and made new OpenAI embedding/generation calls. Its unauthenticated `/query` returned 401; authenticated query returned the expected evidence and reported token usage.

Private local evidence: `.data/release/live-report.json`, `.data/release/standalone-report.json`. Reproduce with `python tools/verify_live.py --allow-model-calls`, which explicitly permits new billable calls. `node tools/review_saved_run.mjs` only reads saved runs.

## Rendered visual/replay review

Reviewed 1440×900, 1024×768 and 390×844 with all six live lanes, plus doubled controls/text using Chromium 200% CSS zoom. Desktop has three readable columns, tablet two, mobile a lane selector. Mobile source inspection traps focus; Escape closes it and restores citation focus. Reduced motion preserves all information. Sources, comparison, history, setup and export share controls and typography with progressive detail disclosure.

All 35 observed steps expose purpose, input, action/result and measured duration. Parallel hybrid branches join visibly; rank changes link to the recorded passage; parent expansion links children to parents; PageIndex lists selected sections/pages. No private model reasoning or unobserved internals are fabricated. Replay frames 0/70/140 reconstruct the completed answers with original timings. Previous/next/seek, 4× speed, compressed waits and keyboard citation inspection passed with no browser errors.

The final packing inspector also exposes the exact recorded token count/budget, excluded count and selected passages (`packing-desktop.png`). Initial release readiness and all six technique capabilities passed (`.data/release/readiness.json`).

A final scan found no actual provider key, application token or encryption master key in tracked files or either live export ZIP. The local `.env` has mode 0600. Final test logs and the execution ledger are preserved in `.data/release`; the plan’s generated scratch workspace was cleaned up.

Inspected local screenshots under `.data/release/visuals`: `six-lanes-1440.png`, `six-lanes-1024.png`, `six-lanes-390.png`, `workflow-*.png`, `pageindex-source-mobile.png`, `zoom-200.png`, `replay-start.png`, `replay-middle.png`, `replay-end.png`, `failed-desktop.png` and `cancelled-desktop.png`. Browser screenshots cover connector, export, setup and disconnected states. Machine-readable record: `.data/release/visual-review.json`. Review found and fixed saved-history setup restoration, 200% zoom overflow, initial project-selection races, missing passage identity in reranking, unclear parent-child links and misleading waiting/stop controls on terminal replay.

## Boundaries and operator setup

- OpenAI credentials and local model assets are verified on this machine. Elsewhere operators need provider credentials and a stable encryption master key. PostgreSQL import needs approved host/relation/column policy and a read-only login. No external business database was requested or connected.
- Offline replay controls external model boundaries and uses Qdrant local exact search. It verifies parity, not remote HNSW performance. No-data archives omit source bytes/names, questions, answers and credentials. Included-data exports include only selected frozen snapshots.
- Linux ships CPU-only inference. GPU/CUDA, cloud deployment, load benchmarking, Safari/Firefox, screen-reader user testing and disaster recovery on an external production host were not performed. Zoom was tested through Chromium CSS zoom.
- Cost remains unavailable without a matching price profile; usage is displayed without inventing zero charges. Dependency deprecations and the frontend chunk-size warning are non-fatal.
- OCR, analytical text-to-SQL, live database sync, GraphRAG/RAPTOR, automatic optimization, additional connectors and multi-user SaaS are outside agreed v1. No in-scope adapter or PostgreSQL connector was deferred.

See [acceptance evidence map](docs/18_RELEASE_EVIDENCE.md).

## Independent review and decisions

A fresh `gpt-6-astra` reviewer inspected the whole implementation without making changes or model calls. It found three Important issues, all reproduced by failing regressions and fixed: preserve pre-start lane cancellation during replay; visibly report actual PageIndex depth/node/call/page truncation; retain and display the recorded context-packing decision. The full suite and rendered review then passed. No Critical or Minor findings, and no behaviors declined for judgment. No second review is claimed.

Execution rulings, in order:

1. This new repository uses a dedicated initial implementation branch in the requested directory. Cost if wrong: move the branch into an isolated worktree.
2. The pack validator scans specification/fixture files; application checks run separately. Cost if wrong: add future specification directories explicitly.
3. Offline vector replay uses Qdrant local exact search with recorded embeddings while running the actual retrieval/context/tree algorithms. Cost if wrong: remote approximate-search differences require a separate live comparison.
4. Linux uses CPU-only PyTorch; macOS uses its native wheel. Cost if wrong: GPU operators must supply and validate a CUDA lock/build.

Deferred minors: none from the independent review. Documented platform/performance checks above remain unperformed; they are not deferred v1 features.
