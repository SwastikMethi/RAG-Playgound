# Acceptance tests

## How to use this matrix

These are implementation behavior checks. The optional reference answers in fixtures help developers verify source handling and retrieval; end users are not required to prepare a test set. Use deterministic providers for reproducible CI and explicitly separate live provider checks.

Every test has observable pass conditions. Record failures and unperformed external checks in IMPLEMENTATION_STATUS.md.

## Core user journey

| ID | Scenario | Pass condition |
| --- | --- | --- |
| A01 | Upload valid Markdown/text | Source becomes ready with correct text, offsets and hash |
| A02 | Upload text PDF | Physical page numbers and inspectable text survive parsing |
| A03 | Upload scanned/encrypted/corrupt input | Actionable failure; no empty successful index |
| A04 | Freeze corpus and edit source selection | New version created; old run retains its exact membership |
| A05 | Save configuration edit | New revision; old config and run snapshot are unchanged |
| A06 | Prepare twice with identical requirements | Compatible artifacts reused; no duplicate embedding work |
| A07 | Change embedding identity/dimension | New or rejected preparation; no incompatible artifact reuse |
| A08 | Ask while a selected bundle is unready | API rejects before a compare job or query timer starts |
| A09 | Submit one question to four lanes | All lanes start independently; same frozen corpus and shared generation settings |
| A10 | Click an answer citation | Exact supplied evidence and original source location open |
| A11 | Ask an unsupported question | No fabricated source IDs; insufficient evidence is visible |
| A12 | Give feedback and rerun | Feedback persists; rerun has new identity and linked parent |

## Technique correctness

| ID | Scenario | Pass condition |
| --- | --- | --- |
| R01 | Query unique NEBULA-42 identifier | Actual BM25 returns the containing source above nonmatching material |
| R02 | Empty lexical overlap | BM25 produces zero candidates, not arbitrary top documents |
| R03 | Dense search across two projects | Only the specified corpus/index scope is returned |
| R04 | Known hybrid rank lists | RRF values, deduplication and stable ties match hand-calculated expected ranks |
| R05 | Fixed reranker outputs | Before/after ranks and candidate IDs agree with real sorting |
| R06 | Several child hits in one parent | Parent appears once with correct child links and original offsets |
| R07 | Oversized parent | Context respects budget and clipped citation spans match actual supplied text |
| R08 | PageIndex local compatibility | Actual SDK indexes a text PDF and returns readable tree/page evidence |
| R09 | PageIndex with mixed corpus | Card and API reject unsupported combination; no silent document exclusion |
| R10 | Tree model returns unknown IDs | Reject or bounded repair; never read arbitrary pages or paths |
| R11 | Tree limits reached | Stop at configured call/depth/page caps and emit a warning |
| R12 | Embedding provider silently truncates | Application prevalidation catches oversized chunks or marks unsupported tokenizer capability |

## Timing and event integrity

| ID | Scenario | Pass condition |
| --- | --- | --- |
| E01 | Hybrid branch delays overlap | Retrieval metric measures wall duration, not sum of branch durations |
| E02 | Answer token arrives after internal tree calls | TTFT starts with final-answer text, not retrieval model output |
| E03 | SSE reconnect after sequence N | Events after N resume; no duplicated deltas or model calls |
| E04 | Duplicate and out-of-order frames | Duplicates ignored; gaps trigger resync; reducer does not invent state |
| E05 | Unicode answer with emoji | Code-point offsets and final UTF-8 text hash validate |
| E06 | Full replay versus live final state | Answers, citations, rankings, statuses and metrics are identical |
| E07 | Slow animation or compressed replay | Server timings remain unchanged |
| E08 | Cancel one running lane | That lane terminates; other lanes continue |
| E09 | Cancel before job start | No model call; query timings remain null |
| E10 | Timeout in one lane | Partial evidence preserved and run aggregates correctly |
| E11 | Worker loses lease | Old owner is fenced; no late answer appends; unfinished lanes fail explicitly |
| E12 | Same idempotency key reused | Same body returns original resource; changed body returns 409 |
| E13 | No evidence | Generation skipped, TTFT null, answer_kind insufficient_evidence |
| E14 | Provider wait/retry | Wait and attempts visible; timings are not reduced to conceal them |

## Data access and export

| ID | Scenario | Pass condition |
| --- | --- | --- |
| S01 | Access stream/file/export without token | Request denied and no protected bytes delivered |
| S02 | Unsafe Markdown/HTML in source or answer | Script and unsafe links cannot execute |
| S03 | Prompt-injection fixture | No tools executed or credentials exposed; content stays evidence data |
| S04 | Disallowed database host/schema | Connection/capture rejected with a safe error |
| S05 | Hostile relation/column name | Quoted identifier handling remains safe; arbitrary SQL cannot be supplied |
| S06 | Database row or byte limit reached | Snapshot caps hold and UI reports truncation and ordering |
| S07 | Database changes after capture | Existing run answers from frozen captured text without a live DB read |
| S08 | Source deletion while run active | RESOURCE_BUSY; after stopping, confirmed cascade deletes derived content |
| S09 | Cross-project source/config/bundle references | API rejects mismatched ownership before execution |
| X01 | Export no-data default | No user document bytes, source excerpts, query text, answers, keys or connection secrets in ZIP |
| X02 | Export with included snapshots | Only selected corpus data included, hashes match and citations rebuild |
| X03 | Clean export startup | Import, setup and actual documented query command work without the playground service |
| X04 | Offline export replay | Evidence IDs/order, packed context and source mapping match recorded external-boundary replay |
| X05 | Live export check not requested | UI and manifest say not performed; no verified-live badge |
| X06 | PageIndex export | Actual adapter/controller and index rebuild path included; no dense fallback |
| X07 | ZIP path attack or symlink | Build rejects traversal and unexpected filesystem entries |

## Interface quality and simulation clarity

These checks apply to the implemented UI, not the documentation. Use representative fixture runs and inspect the rendered screens in addition to automated interaction tests. Follow document 13's visual system and viewport/state review requirements.

| ID | Scenario | Pass condition |
| --- | --- | --- |
| U01 | Sources, compare, history and export views | Shared typography, spacing, controls and restrained color form one coherent interface; no decorative clutter or unexplained primary actions |
| U02 | First comparison view | Question, lane identity, status, answer, citations and primary time are easy to locate; explanation and technical detail are available through consistent labeled controls |
| U03 | Four to six lanes at required viewports | Answers remain readable through scrolling or switching; controls do not overlap or cause page-level horizontal overflow |
| U04 | Long answer, filename, ID and candidate list | No layout break or silent loss of content; full answer/source name is accessible; technical data scrolls or expands within its region |
| U05 | Inspect any observed step in every adapter | Panel clearly states name/state, purpose, input, observable action/result and duration; raw trace knowledge is unnecessary |
| U06 | Inspect hybrid and reranking runs | Parallel branches and join are clear; the same passage can be tracked through branch membership and before/after rank |
| U07 | Inspect parent-child and PageIndex runs | Child-to-parent evidence and node-to-page links are understandable; unavailable internals and adaptive future steps are not fabricated |
| U08 | Step forward/backward during replay | All intermediate events are reduced correctly; final state matches full replay; answer tokens do not become hundreds of separate visible steps |
| U09 | Inspect a completed step while live events arrive | Selected panel and keyboard focus stay stable; Follow live is explicit; graph nodes do not jump during streaming |
| U10 | Slow, fast and compressed playback | Step output remains inspectable; playback mode is clear; original measured times never change and backend work is not delayed |
| U11 | Empty, waiting, streaming, failed, cancelled, disconnected and unavailable states | State and next action are clear; consequential warnings remain visible; no fake percentage, output or unavailable-as-zero metric |
| U12 | Keyboard, reduced motion and 200% zoom | Core actions and step inspection remain usable; no essential information depends on hover, color or animation alone |
| U13 | Final visual and replay review | IMPLEMENTATION_STATUS.md records viewport/state coverage, representative screenshots and replay recording or frame sequence; no unresolved clipping, unreadable lanes or missing step explanations |

## Real provider smoke checks

Use a small owner-approved corpus and explicitly configured profiles. Verify embeddings, streamed generation, recorded usage where available, valid source links and cancellation behavior. Exercise the actual reranker weights and PageIndex tree APIs.

Avoid asserting that a stochastic answer must equal a fixed sentence. Check citation membership, evidence availability and application behavior, and manually inspect factual output. Record model/profile identity and date.

If no credentials or model weights are available, CI may pass deterministic checks while live integration remains unverified. The completion report must say so.

## Release checklist

- All six selectable v1 techniques use real implementations and correctly advertise compatibility.
- PostgreSQL snapshots use selected text and remain immutable.
- The question runs concurrently across selected lanes without one lane's failure blocking another.
- Query timers exclude indexing and distinguish retrieval, TTFT and completion.
- Graphs represent recorded operations and have an accessible stage-list alternative.
- Mature visual design, appropriate information density and crisp step explanations pass the U-series checks with rendered UI review evidence.
- Refresh, reconnect, replay, cancellation and worker recovery are tested.
- Export runs independently, preserves runtime provenance and reports verification honestly.
- Security and deletion gates pass; secrets are absent from artifacts and operational logs.
- Setup commands, migrations, environment examples and supported limits are documented.
- Unperformed external checks and later backlog items are listed precisely.
