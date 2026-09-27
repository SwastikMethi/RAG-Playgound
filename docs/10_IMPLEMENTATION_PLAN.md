# Implementation plan

## Delivery approach

Implement a working vertical slice, then expand through milestones M0 to M8. Each milestone has a runnable result and a behavioral gate. Continue beyond the first slice to the complete v1 scope. Use IMPLEMENTATION_STATUS.md to record task completion and evidence.

A missing model key can block a live check without blocking source handling, contracts, UI, deterministic runtime tests or the exporter. Identify that distinction explicitly. Time estimates are intentionally omitted because the existing repository and available model infrastructure determine the work.

## M0 Foundations and contract validation

- T001 Inspect the repository and merge applicable guidance. Choose the documented stack or record compatible existing-stack adaptations.
- T002 Create frontend, API, shared runtime and worker packages with compatible pinned dependencies and lockfiles.
- T003 Implement server configuration, application-token authorization, health/readiness and sanitized provider profiles.
- T004 Implement PostgreSQL migrations, scoped repositories, artifact storage and the durable job claim/lease mechanism.
- T005 Integrate JSON Schema/OpenAPI validation and shared frontend request/event types.
- T006 Add deterministic provider interfaces and synthetic fixtures strictly for tests and labeled preview mode.
- T007 Establish shared visual tokens, typography, spacing, controls and the workspace shell from document 13. Build reusable status, metric and inspector components before styling screens independently.

Gate: Compose starts on loopback without an application token, migrations are repeatable, cross-origin API requests fail, contracts load, worker claims are exclusive, and the fake provider cannot activate silently in live mode.

## M1 First real vertical slice

- T101 Implement PDF, Markdown and text upload, bounded parsing, source status and evidence preview.
- T102 Implement immutable corpus versions, fixed-token chunks and a ready BM25 preparation bundle.
- T103 Implement configuration persistence, compare request creation, independent lane state and core event persistence.
- T104 Implement real BM25 scoring, common context packing, a configured compatible streaming answer provider and citation resolution.
- T105 Create the basic comparison panel with actual stream events, source drawer, independent status and measured timings.
- T106 Add run history and authorization for event streams and source artifacts.
- T107 Apply the overview/explanation/technical-detail hierarchy. Inspect the first rendered source and answer screens for readability, stable layout and clear actions at desktop and mobile widths.

Gate: A user uploads the fictional Markdown fixtures, prepares BM25, asks a question and gets an inspectable result. Test actual BM25 behavior with a deterministic generator. Run a separate live-generation smoke check if credentials are present; otherwise mark only that check unverified.

## M2 Dense and hybrid comparison

- T201 Add Qdrant preparation, scoped payloads, dimension validation and exact cosine search.
- T202 Implement dense query embedding and independent per-lane provider accounting.
- T203 Implement two-branch hybrid retrieval, stable RRF and rank provenance.
- T204 Add the local cross-encoder reranker, pinned weight revision, bounded resource loading and before/after ranks.
- T205 Implement multiple saved configurations of one technique and shared generation validation for comparison requests.
- T206 Add compatible artifact reuse, readiness checks and explicit index-build versus query timing.

Gate: BM25, dense, hybrid and hybrid_rerank run together on the same corpus. A failed reranker lane does not interrupt the others. Dense search cannot return another project's chunks.

## M3 Visual traces and resilient streaming

- T301 Implement the typed event reducer shared by live and replay UI.
- T302 Build fixed workflow graphs and an accessible stage list with input/output inspection.
- T303 Visualize hybrid branch membership, fusion ranks and reranker changes.
- T304 Implement SSE resume, duplicate suppression, snapshot reconciliation and Unicode-safe delta offsets.
- T305 Add pause, seek, step and playback speed with a separate measured time ruler.
- T306 Implement lane/run cancellation, deadlines, rate-limit warnings and worker-loss fencing.
- T307 Implement consistent step explanations, stable selection/Follow live behavior and step-level replay boundaries over the existing reducer. Keep parallel branches and before/after evidence changes clear.

Gate: A recorded run replays to exactly the same final state. Reloading mid-answer does not repeat text or submit another query. One lane can stop while another completes. A selected step clearly explains its purpose, input, action/result and duration; step-level playback preserves intermediate events and true branch concurrency.

## M4 Hierarchy and PageIndex

- T401 Implement parent sections, child chunks, parent expansion and source-offset provenance.
- T402 Validate the installed PageIndex SDK with a text-PDF compatibility probe and pin the tested version.
- T403 Implement the actual PageIndex preparation adapter and bounded controller described in document 04.
- T404 Normalize page and tree-node provenance and add live tree selection inspection.
- T405 Add input restrictions, model-call budgets, malformed-selection handling and explicit unavailable states.
- T406 Add fixtures exercising parent/child mappings, node-to-page mappings and tree-controller cancellation.

Gate: All six techniques are implemented. PageIndex uses its actual tree API and shared final answer generation. Its card is disabled for non-PDF/mixed corpora and does not silently exclude sources. If a live dependency is inaccessible, the feature remains explicitly unverified until tested; no stub counts as complete.

## M5 PostgreSQL text source

- T501 Add encrypted connection persistence, allowlisted network destinations and sanitized metadata APIs.
- T502 Introspect allowed relations, fields and candidate stable keys.
- T503 Implement bounded read-only repeatable-read snapshot capture, quoting identifiers safely.
- T504 Add selection UI, preview, capture progress, truncation disclosure and row-level citation inspection.
- T505 Support snapshot refresh as a new source revision and corpus version.
- T506 Test read-only permissions, hostile identifiers, duplicate keys, null records, row limits, byte limits and timeouts.

Gate: A developer imports selected fixture-table text, asks a question without reconnecting to PostgreSQL, and can inspect the exact captured row. Writes and arbitrary SQL are impossible through this connector.

## M6 Portable export

- T601 Package the same runtime revision, configuration, source manifest and required dependencies.
- T602 Implement include_data=false as the default and explicit source inclusion.
- T603 Generate runnable ingest/query/API commands, setup instructions, environment placeholders and third-party notices.
- T604 Implement static validation and offline replay with recorded external boundaries.
- T605 Offer optional live replay with clearly reported verification status and differences.
- T606 Cover all six v1 adapters and database snapshots, preserving model and source provenance.

Gate: A clean temporary environment can run the exported package; deterministic evidence/context replay matches. The no-data archive contains no document excerpts, database rows, original question text, answers or secrets.

## M7 Product completion and operational hardening

- T701 Finish feedback, preferred-lane notes, history filters and rerun navigation.
- T702 Complete source deletion impact, busy-resource rejection and dependency cleanup across all stores.
- T703 Verify Markdown/PDF rendering safety, same-origin access across APIs/streams/downloads and error redaction.
- T704 Add resource limits, health diagnostics, dependency-unavailable messages and cleanup of partial artifacts.
- T705 Test keyboard navigation, reduced motion and useful mobile lane switching.
- T706 Document setup, provider profiles, database roles, backup/rebuild, common errors and actual limits.
- T707 Review all core screen states against document 13 and the U-series acceptance matrix. Fix clutter, inconsistent hierarchy, clipped controls, unnecessary decoration and unclear simulation transitions. Record representative screenshots and a replay recording or frame sequence.

Gate: The complete main journey works without developer-only endpoints or hidden manual steps.

## M8 Release verification

- T801 Run the acceptance matrix in document 11 and record actual evidence.
- T802 Run a live smoke comparison using each available adapter with a small owned fixture.
- T803 Verify export replay for one chunk-based and one tree-based lane, then exercise the remaining adapter export paths in integration tests.
- T804 Confirm no unimplemented selectable controls, fake production fallbacks or automatic quality-winner claims.
- T805 Complete IMPLEMENTATION_STATUS.md with verified behavior, setup requirements and precise unverified checks.
- T806 Record the visual review results, viewport/state coverage and remaining design defects. Design quality and simulation clarity must pass their release gates; unperformed visual checks are explicitly unverified.

Gate: The user can start the application, upload/connect, select, ask, inspect, replay, adjust and export. Do not deploy publicly as part of this milestone.

## Later backlog

Order later work from actual user feedback: OCR and additional document types; contextual retrieval and query rewriting; optional batch-question comparisons; RAPTOR and GraphRAG with source lineage; additional database connectors; live sync; existing-pipeline integration; multi-user hosting. Each new adapter requires trace and export contracts, not just a new selection card.
