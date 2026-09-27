# Implementation status

M0–M8 implementation, release checks and independent whole-branch review are complete on `codex/implement-rag-playground`. Scope: [execution plan](docs/14_EXECUTION_PLAN.md). Release gate: [document 11](docs/11_ACCEPTANCE_TESTS.md). No public deployment was performed.

## Working application

All six real adapters are implemented: BM25, scoped Qdrant dense retrieval, parallel hybrid RRF, hybrid with a pinned local cross-encoder, parent-child and experimental PageIndex. The application includes file ingestion, frozen PostgreSQL text snapshots, immutable corpus/configuration revisions, preparation reuse, independent streamed answers and citations, measured execution graphs, persisted replay, source inspection, manual feedback, history, reruns, confirmed retryable deletion and standalone export using the same runtime.

Start with [README.md](README.md) or [operating instructions](docs/17_RUNNING_THE_APPLICATION.md). After setup, use `./start.sh` and `./stop.sh` to manage the API, worker and local storage services. Local URL: `http://127.0.0.1:8780`; the workspace opens directly without a login or application token. Configure `OPENAI_API_KEY` in `.env`, never in `.env.example`. Private credentials already supplied on this machine were kept out of Git.

## Hosted public beta — 27 September 2026

Implementation is on `codex/free-hosting` in `.worktrees/hosted`. [Plan](docs/19_HOSTED_DEPLOYMENT_PLAN.md), [deployment and restore runbook](docs/20_HOSTED_DEPLOYMENT.md). **No public deployment:** the owner confirmed there is no Oracle account or VM yet. Existing local uploads, the running local application and owner-managed model configuration were preserved.

Hosted mode adds username signup/login, Argon2id password hashes, single-use recovery codes, revocable Secure/HttpOnly cookie sessions, Origin/CSRF checks, persistent account/IP throttling and Turnstile validation. All data endpoints are scoped to the project owner, including events, evidence, source files, connections and exports. Streams stop after session revocation. Individual OpenAI keys are Fernet-encrypted, injected per job and excluded from manifests/fingerprints. Missing keys cannot fall back to an owner environment key. Local mode remains token-free on loopback.

Production Compose uses Caddy HTTPS, private PostgreSQL/Qdrant, persistent data/model volumes, a registered non-root application user, memory caps, two worker slots and one active comparison. Admission limits are five projects, 500 MiB raw uploads, 2 GiB artifacts, 100,000 vectors, 64 queued jobs per user/256 total and a 20 GiB disk reserve. New vector/HNSW storage is disk-backed. A secret initializer, quiescent OCI backup script, three-checkpoint retention and a read-only restore verifier are included; no paid fallback or infrastructure was provisioned.

Release verification:

- Final Python suite: **80 passed**, four existing dependency warnings, 155.84 seconds. Five frontend tests, eight browser tests, production build, Ruff, shell syntax, pack/OpenAPI validation (53 operations), production Compose validation and Caddy configuration validation passed. Vector-memory and startup-secret-redaction regressions passed after reproducing the failures.
- Browser evidence: signup/login/recovery at 1440, 1024 and 390 px; keyboard tab/focus, reduced-motion preference, disabled recovery confirmation, masked key save/remove and error states. Reviewed `.data/release/hosted/login-1024.png`, `recovery-390.png`, `key-saved-390.png`, `key-error-1440.png` and `login-zoom-1024.png`. The additional 200% Chromium CSS zoom check passed without horizontal overflow. Existing source/answer/replay/export/PostgreSQL/50-file journeys still pass. Account browser tests label their API/Turnstile fixtures; real auth, revocation and ownership are tested against PostgreSQL separately.
- Live hosted smoke used an operator-seeded test account, a real session, a Fernet-stored individual OpenAI key and only an authored fictional PDF. All six preparations/answers completed with evidence; 19 ordered answer deltas persisted; cancellation succeeded. Dense and PageIndex exports passed static, offline and live replay. Dense live answer wording differed while evidence order matched, which is expected for stochastic generation. Report: `.data/release/hosted-live/live-report.json`. This does not verify real Turnstile or human source correctness.
- Isolated restore into separate Linux ARM PostgreSQL/Qdrant/app containers passed before and after restart: 20 artifact hashes, one decryptable credential and two vector scopes matched; anonymous data requests returned 401. Used a PostgreSQL dump, artifact copy and native Qdrant snapshots of the isolated live fixture. Report: `.data/release/hosted-restore/report.json`. This is not an OCI-native volume restore.
- ARM64 image built. A real PDF/reranker test found Torch requires a registered UID; the Dockerfile now creates that user. With a valid account name, Linux `aarch64`, CPU Torch 2.11.0, Docling parsing, actual MiniLM scoring and PageIndex 0.2.19 all passed. After the final rebuild, the API/worker restarted as UID 10001 (`rag`); health and all restored artifact/credential/vector checks passed again. Image: `sha256:030d76df4d81e322e7fbc4708ab250c4ee9b367e4e605ea0b6b03f66d40c0630`.
- The isolated Caddy check first failed with an upload connection held beyond 65 seconds. With request deadlines, it closed at 60.0 seconds; a complete 1 MiB body reached the Session/Origin guards and health remained 200. `python tools/verify_proxy.py http://127.0.0.1:18888` is the runnable check. Streamed responses have no write deadline.
- Exact-secret scans of repository files and both live export ZIPs passed. No production/provider credentials were committed; test data and reports remain ignored/private.

Launch still requires Oracle Always Free capacity, VM/SSH access, DuckDNS hostname, Turnstile keys and fresh production secrets. Real public HTTPS/Turnstile, firewall exposure checks and an OCI volume backup/restore remain explicit H08 launch gates. Free hosting does not cover users' OpenAI usage. Backups have a maintenance window; metadata admission uses one short global lock. These are deliberate small-beta limits, not enterprise availability promises.

A fresh independent reviewer found no Critical issues, three Important issues and one Minor issue. The single fix pass binds live-export credentials to controlled subprocess aliases (including explicitly empty keys), reserves vector capacity before billable embedding, and sets Caddy request-header/body deadlines without limiting streamed response writes. Export alias changes with and without a stored user key, vector rejection before provider calls, and proxy connection deadlines each failed first and then passed. The full suite passed after these changes. No second independent review is claimed.

Hosted implementation rulings, in order:

1. Work in an isolated checkout and reuse installed dependencies. This preserves the original app; the release must be used from `codex/free-hosting`.
2. Finish the tested handoff without a cloud account; no paid fallback. Public deployment remains unverified until a free VM exists.
3. Use a short global metadata lock for atomic quotas. Larger deployments will need finer-grained coordination.
4. Give browser subprocesses an explicit worktree import path. Shared editable dependencies otherwise load the original checkout; ordinary independent checkouts need no workaround.
5. Implement storage admission with account scoping because they share a transaction boundary. The same global metadata throughput ceiling applies.
6. Store new vectors/HNSW on disk to fit the 2 GiB Qdrant cap. Cold reads may be slower; existing collections are unchanged.
7. Keep public TLS/Turnstile/OCI networking and native restore as H08 launch gates, since the reviewer could not judge a nonexistent deployment. They must pass before public launch.
8. Accept the approved single-host worker/metadata design. Horizontal scale and large-load performance are unverified.
9. Keep project deletion/archive and metadata retention outside this increment. Sources can be removed and projects reused, but the five-project cap has no project-slot reclamation path in this beta.
10. Keep infrastructure free-only and backup monitoring manual. Availability and unnoticed backup failures depend on operator checks.
11. Preserve the owner's dirty model configuration unstaged; production uses `deploy/profiles.yaml`. Those local choices are excluded from the portable release.

Deferred minor: local missing-key guidance points to Setup, although local mode reads `OPENAI_API_KEY` from `.env`. The README and operating guide contain the correct local instructions. This does not affect hosted key setup or credential isolation.

## GPT-6 Luna provider compatibility — 27 September 2026

Reproduced the reported provider failure: GPT-6 Luna rejected `max_tokens`, then rejected `temperature: 0` under its default reasoning setting. Model-access checks succeeded, and the existing run's retrieval/embedding/reranking stages had completed. Added typed server-profile options for the completion-token parameter and reasoning effort, used by both streamed answers and non-streaming PageIndex calls. The local answer profile now sends `max_completion_tokens` and `reasoning_effort: none`. Preserved the owner's model choices and embedding configuration. Default options retain legacy profile fingerprints, so existing prepared vector indexes remain valid. HTTP 400/422 provider errors now explain rejected request settings without exposing upstream bodies or credentials.

Regressions first failed for the missing options and generic errors, then passed for both generation paths, legacy profiles, fingerprint compatibility, error redaction and no retry of invalid settings. Final Python suite: 63 passed, four dependency deprecation warnings, 116.50 seconds. Ruff, pack validation and the startup production build passed. No frontend screens changed.

Live verification through the implemented gateway passed for streaming text and JSON completion with GPT-6 Luna (64-token caps, synthetic prompts). After confirming no queued/running jobs, restarted API and worker; readiness returned `ok`. Retried the previously failing question in a new live BM25/dense comparison using the exact existing bundles: both lanes completed, cited E1/E2/E3 labels present in their context, and persisted 14 answer deltas. Citation checks establish reference validity, not human verification of source correctness. The embedding profile fingerprint remained unchanged; no source re-upload or index rebuild was performed. Private verification records: `.data/release/provider-compatibility/live-gateway.json` and `live-run.json` (run `89c43bfc538547e9b0c05c0f3ca4e0f0`). The existing failed run remains immutable.

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
