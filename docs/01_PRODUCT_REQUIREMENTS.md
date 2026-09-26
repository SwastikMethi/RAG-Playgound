# Product requirements

## Purpose

RAG Playground helps developers learn and compare retrieval-augmented generation approaches using their own documents and questions. The user sees answers, supporting evidence, elapsed time and a visual trace of what each selected pipeline did, then exports a working implementation. The product's first responsibility is making experiments understandable and inspectable.

The agreed experience is upload or connect, select, prepare, ask, compare, inspect, adjust and export. There is no mandatory ground truth, synthetic evaluation questionnaire, judge model or automatic winner.

## Users and decisions

The primary user is a developer prototyping a document assistant. A learner uses the same interface to understand retrieval, fusion, reranking, hierarchy and tree navigation. Both should be able to explain where an answer's evidence came from and identify whether an observed difference came from retrieval, context selection or generation.

The first release is a single-owner, self-hosted web application. It is intended for bounded experiments. Hosted multi-user isolation and production traffic guarantees are separate work.

## Required user stories

| ID | User story | Completion condition |
| --- | --- | --- |
| US01 | Upload source documents | User sees per-file progress, extraction preview, provenance and actionable failures |
| US02 | Import text from a database | User selects an approved read-only PostgreSQL source, relation and fields, then creates an immutable snapshot |
| US03 | Select approaches | Registry explains each technique and disables unsupported combinations with a reason |
| US04 | Prepare configurations | Required artifacts are prepared once, readiness and setup time are visible, identical artifacts may be reused |
| US05 | Ask once | One request creates one run with 1 to 6 lanes, ordinarily 2 to 4 selected for comparison |
| US06 | Compare answers | Each lane streams independently with citations, status and measured timings |
| US07 | Understand execution | User opens a stage and understands its purpose, input, action, result and duration without reading raw trace data |
| US08 | Replay execution | User pauses, seeks, steps and changes playback speed without rerunning models |
| US09 | Experiment again | User edits settings into new configuration revisions and reruns a question |
| US10 | Record preference | Helpful or unhelpful feedback, notes and an optional preferred lane persist |
| US11 | Reuse implementation | User downloads code, configuration, setup instructions and provenance for a completed lane |
| US12 | Control data | User can delete source-dependent artifacts and history with an explicit impact summary |

## Functional requirements

- FR01 Files: text-layer PDF, UTF-8 Markdown and UTF-8 text are required. Preserve source boundaries and PDF page numbers. Reject encrypted, malformed and image-only PDFs with a clear message; OCR is deferred.
- FR02 Database: support a read-only PostgreSQL table or view with an explicit stable key, selected text columns and optional updated-at column. No arbitrary SQL editor or joins in v1.
- FR03 Corpora: runs reference immutable corpus versions. Adding or removing a source creates a new version.
- FR04 Adapters: release v1 includes bm25, dense, hybrid, hybrid_rerank, parent_child and pageindex.
- FR05 Compatibility: PageIndex v1 accepts only all-PDF corpora with a text layer and no more than 10 PDFs. Incompatible data must disable that lane, not silently omit documents.
- FR06 Configurations: users can save multiple configurations of the same technique; each selected configuration becomes a separate lane.
- FR07 Preparation: no indexing runs inside a query timer. Queries require every selected bundle to be ready and matched to the frozen corpus and configuration.
- FR08 Fan-out: all selected lanes become eligible together in parallel mode. Provider and CPU resource waits remain visible and count in lane totals.
- FR09 Answers: stream text and resolve citation IDs to source evidence. A generation failure does not erase retrieved evidence or block other lanes.
- FR10 Visualization: show actual stage transitions and evidence movement. Node labels and candidate ranks use recorded data.
- FR11 Metrics: show queue time, retrieval time, time to first answer token and lane total. Optional token usage and price estimates must have completeness labels.
- FR12 History: preserve question, lane configuration, corpus version, artifacts, trace, feedback and terminal status.
- FR13 Replay: recover after refresh or dropped stream without duplicate answer text, duplicate stages or new provider calls.
- FR14 Cancellation: allow one lane or the entire run to be stopped. Preserve partial output and account for already incurred usage.
- FR15 Export: export every completed supported v1 technique through the shared runtime. Optional inclusion of source snapshots must be a separate explicit choice.
- FR16 Errors: distinguish invalid configuration, unsupported input, missing credential, rate limit, timeout, cancellation and internal execution failure.
- FR17 No-answer behavior: zero useful evidence produces an insufficient-evidence result with an empty or partial source list; no invented citations.
- FR18 Provider setup: an owner configures server-side provider profiles and model IDs. The browser selects public profile metadata and never receives credentials.
- FR19 Access: an application token protects the single-owner instance. Downloads and event streams require the same authorization as other data.
- FR20 Deletion: deleting a source is blocked while dependent jobs are active. User stops those jobs, reviews the impact and confirms cascade removal.
- FR21 Design quality: deliver a mature, coherent interface with shared typography, spacing, restrained color and consistent controls. Keep the main task uncluttered through the overview/explanation/technical-detail hierarchy in document 13.
- FR22 Simulation clarity: each observed step has a concise name, purpose, input, action/result, state and duration. Show true branching and evidence changes, with focused inspection and step-level replay. Missing outputs and unobserved internals are labeled honestly.

## Design quality requirements

The user's direction is a professional, deliberately designed product whose detail is easy to understand and present in the right amount. Treat document 13 and the U-series acceptance checks in document 11 as release requirements. Core answers, status, citations and consequential warnings remain visible; secondary and technical detail are available through predictable, labeled controls. Simulation clarity requires inspecting the rendered workflow and step explanations, not just proving that events exist.

## Scope boundaries

| Included in v1 | Later extension |
| --- | --- |
| Six instrumented retrieval adapters | GraphRAG, RAPTOR, contextual retrieval, query rewriting, HyDE, ColBERT |
| Text PDFs, Markdown, text | DOCX, scans, images, multimodal parsing |
| PostgreSQL text snapshots | Analytical text-to-SQL, live sync, other SQL engines, vector-store imports |
| Preset pipelines with editable parameters | Arbitrary workflow authoring |
| Manual comparison and feedback | Optional batch evaluations and automatic optimization |
| Local single-owner access | Hosted tenants, sharing, SSO and project roles |
| Self-contained Python export | Multiple framework or programming-language export targets |

The extension list records intended expansion without pretending those features are implemented. Nearest-neighbor search is an index/search setting under dense retrieval, not a distinct semantic RAG family.

## Default limits

These are product safeguards and testing envelopes, not measured capacity claims. Administrators can lower them.

| Item | Initial limit |
| --- | --- |
| Sources per corpus | 20 files or snapshot sources |
| One uploaded file | 20 MiB |
| Total raw corpus bytes | 100 MiB |
| Total PDF pages | 500 |
| Parsed text | 2,000,000 Unicode characters per corpus |
| Prepared chunk count | 10,000 per chunk variant |
| PostgreSQL import | 10,000 rows and 20 MiB serialized text, whichever is reached first |
| Lanes per question | 1 to 6 |
| Active compare runs | 2 per instance |
| Question length | 8,000 characters |
| Lane timeout | 90 seconds by default, configurable up to 300 seconds |
| Generation output | 512 tokens by default |
| Context budget | 3,000 tokens by default, reduced when provider capacity requires |
| PageIndex documents | 10 text PDFs per corpus |

Limits must be enforced server-side and displayed before an operation where possible. A capped database snapshot displays its truncation and sampling policy.

## Release definition

All required stories, six adapters, database snapshots, real traces, cancellation, event recovery, export and design quality must pass the applicable gates in document 11. Missing optional infrastructure can disable a technique in an installation, but cannot be represented as completed implementation work. PageIndex must have a tested public-API integration path and an honest unsupported or unavailable state.

Success is a completed user journey with inspectable evidence and usable code. Product analytics, if added, should count run completion, inspection and export success without collecting document contents by default.
