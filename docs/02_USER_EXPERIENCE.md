# User experience and visual execution

## Interface direction

Create a mature, deliberately designed developer workspace with clear typography, restrained color, generous answer width and readable evidence panels. Make comparison and learning the central activities. Technique cards need a short plain-language description, supported source types and a settings summary. Follow the required visual system, information hierarchy and review criteria in [Design and simulation standards](13_DESIGN_AND_SIMULATION_STANDARDS.md).

The default workspace has a project and corpus sidebar, a question bar, comparison lanes and an evidence drawer. Do not make users build a node graph before asking a question. The graph is a visualization of execution.

Keep three levels of detail: an immediately readable overview, a focused explanation on selection, and expandable technical detail. Use consistent controls to reveal detail. Core status, citations, consequential warnings and next actions remain visible. Only one evidence/settings/step inspector is open at a time.

## Screens

### Project and sources

List projects and their latest corpus versions. The source screen has upload and PostgreSQL import actions. Each source row shows name, type, readiness, size, extraction warnings and a preview action. The preview shows parsed text beside its page or section location. For database snapshots, show relation, selected fields, row count, capture time and whether the row limit was reached.

Creating a corpus version freezes a selected set of ready source revisions. Explain that existing runs retain their old version. A destructive delete action first shows affected corpora, indexes, runs and exports.

### Techniques and preparation

Present six selectable cards with status: compatible, needs preparation, preparing, ready or unavailable. Unavailable cards state a concrete reason such as image-only PDF, missing reranker weights or PageIndex SDK failure. A future roadmap technique is labeled planned and is not selectable.

Default to dense and hybrid_rerank when their dependencies are configured. Otherwise default to BM25 and explain what additional configuration is needed. The same technique can be added twice with different saved settings and distinct lane names.

Setup is the only place to choose answer and embedding models. Show advanced retrieval and generation tuning in a pipeline drawer with effective defaults, units, limits and a reset action, but no model selectors. Save creates a new revision using the current Setup models. Changing only retrieval or generation settings should reuse compatible source/index artifacts; changing chunking or embeddings must prepare affected artifacts.

Prepare is explicit. It first creates immutable replacement revisions for selected pipelines whose actual models or embedding dimensions differ from Setup, then prepares or reuses their bundles. Historical profile identifiers that resolve to the same models and dimensions do not force a revision or paid re-embedding. Show the actual preparation phases, time spent and whether an artifact was built or reused. Ask remains disabled until all selected configurations reflect Setup and have matching ready bundles. Preparation failures stay next to the affected technique.

Preparation runs on an on-demand worker. While work is queued, explain that the worker may be starting after inactivity or finishing earlier work and that this can take about a minute. Replace that notice with the normal preparation progress as soon as processing begins; do not use a blocking application overlay.

### Comparison workspace

The question applies to the frozen selected corpus and configurations. Submission clears the new run's output, preserves prior history, and opens its authorized event stream.

Every lane includes its name, technique, configuration badge, independent status, a timer, streamed answer, citations and tabs for Answer, Workflow, Evidence and Settings. Answer is the default tab. Keep the compact status/timer header and answer prominent; timing breakdown and configuration detail are available through labeled controls. Show Stop while running and group the later Run this lane again, Feedback and Export actions without making each one a competing primary button. A rerun creates a new run and never overwrites a recorded answer.

At desktop widths show two or three comfortable columns; additional lanes scroll horizontally or use a two-row layout. At smaller widths use a lane switcher while keeping run status and question visible. Do not shrink six answers into unreadable narrow columns.

The question bar displays only the shared answer-model name: the Setup selection before a run and the recorded model for an active or historical run. Context/output budgets remain in pipeline settings rather than this compact caption. The comparison header displays the corpus version and a notice that timing reflects this run. v1 enforces identical effective generation settings across lanes in one run. When users inspect separate historical runs with different settings, display those differences explicitly.

A newly submitted comparison may remain queued while the on-demand worker starts or completes earlier work. Show the same localized, accessible explanation used by preparation until the first persisted execution event arrives. Once the run starts, show its recorded queue duration and normal live status. Historical and already-active runs must not be mislabeled as waiting for worker startup.

### Workflow and evidence

The workflow uses a fixed template for the selected adapter and dynamic evidence records. Stage states are pending, active, succeeded, failed, cancelled and skipped. Use text and icons in addition to color.

Selecting a stage opens a drawer containing:

- A short explanation of what this operation does.
- Its observed status and measured duration.
- Relevant input, such as the question, candidate count and a short passage preview.
- The observable action and output, such as rank changes, selected section titles/pages or packed source text.
- Model and resource-wait metadata when relevant, with IDs and raw event fields in expandable technical detail.
- Warnings, errors and what the trace does not expose.

Never label an invented rationale as the model's thoughts. Optional educational explanations are separate descriptive text. Scores are labeled BM25, cosine, RRF or reranker score with their own units; they are not universal confidence percentages.

Each focused step follows the same reading order: name/state, purpose, input, action/result, duration and next dependency. Keep graph labels short and explanations in the inspector. Preserve the user's selected step as new events arrive; offer Follow live to resume automatic focus. Parallel stages retain separate active states and a visible join. Show unavailable output honestly rather than filling a pending panel with sample data.

The evidence inspector displays source name, PDF page or Markdown line/section or database row identity, exact excerpt, score and rank history, retrieval branch membership, and whether the evidence reached the answer model. Clicking a citation selects the corresponding evidence and source location.

Raw database key values and all source excerpts remain protected content. Citation validity means the cited identifier was supplied to the answer model and resolves to evidence; it does not establish that the source proves the claim.

## Technique animations

| Technique | Required visible operations | Inspector detail |
| --- | --- | --- |
| BM25 | Query tokenization, lexical ranking, context packing, generation | Matched terms, native score, source excerpt |
| Dense | Query embedding, vector search, context packing, generation | Model ID, vector dimensions, candidate score and rank |
| Hybrid | Lexical and dense branches, merge and RRF fusion, context packing, generation | Branch ranks, duplicate removal and fused rank |
| Hybrid with reranking | Hybrid branch flow, reranker, selected context, generation | Before and after ranking; candidates dropped |
| Parent-child | Child retrieval, parent expansion, deduplication, context packing, generation | Child-to-parent link and additional surrounding text |
| PageIndex | Document selection, observable tree selections, page reads, context packing, generation | Tree node IDs, depth, titles and selected page ranges |

A two-dimensional embedding scatterplot is not required. If one is later added, label it as a projection rather than a depiction of how the index internally searches.

## Live timing and replay

While a lane is running, animate its displayed elapsed time using the latest server value and a local monotonic clock. On termination replace it with the final server timing. Stop the extrapolation on disconnect and show reconnecting; do not let an apparently live timer conceal a lost connection.

Recordings replay without model calls. Default controls: play or pause, next step, previous step, seek, speed 0.5x, 1x, 2x and 4x. Technical detail also offers raw-event stepping. Step controls use the presentation boundaries defined in document 07. Gaps may be compressed for teaching, but the UI labels compressed playback and always keeps original measured times visible.

The reducer must produce the same final answer and stage state from full replay and from a live stream with duplicates removed. Seek rebuilds state from events up to the selected sequence. Never use animation completion as evidence that a backend stage completed.

## Failure and empty states

| Situation | Required behavior |
| --- | --- |
| Missing provider key | Setup guidance before Ask; preserve configurations |
| One lane fails | Keep other lanes running and show the failing stage and partial evidence |
| Zero candidates | Explain insufficient evidence; avoid fabricated citations |
| Rate limited | Show provider wait/retry warning with cancellation available |
| Stream lost | Reconnect using the last persisted event sequence; no resubmission |
| Worker stops | Preserve history and show explicit interrupted execution failure |
| Unknown cost | Show unavailable or partial, never a zero-dollar estimate |
| Incompatible PageIndex corpus | Explain that v1 supports text PDFs only; keep other techniques usable |
| Source deleted | Affected historical content is removed by the confirmed cascade |
| Export parity unchecked | Display what was verified and what remains unverified |

## Accessibility and rendering

Provide keyboard access to every node through a corresponding stage list. Respect reduced-motion settings. Streamed text should not announce every token to screen readers; announce meaningful state changes and the completed answer. Use accessible status contrast and do not rely on red/green alone.

Render answers and uploaded Markdown through a sanitized renderer. Disable embedded HTML, scripts, iframes, unsafe protocols and automatic external-resource loading. PDFs load through an authorized application endpoint, not an arbitrary user-supplied URL.

Use React Flow for the graph view if the compatibility check succeeds, with a normal DOM stage list as the accessible equivalent. Keep graph layout stable during streaming so users can inspect an active node without it moving.

Render and inspect the screen states and viewport sizes in document 13. Passing API tests does not establish that details are readable, hierarchy is clear or the simulation is understandable. The U-series acceptance checks are required before release.
