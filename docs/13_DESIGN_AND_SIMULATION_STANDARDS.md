# Design quality and simulation clarity

## Required product character

The user's direction is a mature, carefully designed product with the right amount of information and crisp, understandable simulations. Treat this as a v1 requirement, not optional visual polish. The interface should feel consistent and deliberate across sources, comparison, workflow, history and export. A functioning generic dashboard is not sufficient.

Use a calm, precise developer workspace. Give each screen a clear purpose, a visible current state and an obvious next action. Prioritize readable answers, understandable evidence and direct controls. Documents 02 and 07 define the interaction and timing behavior; this document defines the presentation quality required throughout.

## Visual system

Define shared tokens and reusable components before building individual screens. The following is the initial design direction; adjust values together when needed for accessibility or the existing application's design system. Record intentional deviations rather than accumulating page-specific styles.

| Element | Required direction |
| --- | --- |
| Color | Neutral canvas, quiet surfaces, dark readable text and one restrained accent for the primary action and selection. Reserve semantic colors for status. |
| Typography | One highly legible UI sans-serif family. Use monospace only for code, identifiers and values that benefit from alignment. Default body/answer text 16 px with comfortable line height; secondary UI text 14 px; metadata at least 12 px. Do not shrink essential content to fit more lanes. |
| Hierarchy | Distinguish page title, section title, body and metadata consistently. Headings identify tasks or content; avoid oversized marketing headlines inside the workspace. |
| Spacing | Use a shared 4 px spacing scale, ordinarily 8–12 px within related controls and 16–24 px between groups. Space communicates grouping; excessive empty space must not push the question or result out of view. |
| Surfaces | Subtle borders, restrained 6–10 px corner radii, and minimal shadows. Use separators or tables where another nested card would add clutter. |
| Controls | Consistent sizes, alignment, labels, focus treatment and disabled states. Use one clearly emphasized action per task area; keep secondary actions visually quieter. |
| Icons | One coherent icon set. Use icons to support a recognizable action or state, with accessible names. Explain unfamiliar actions with text. |
| Numeric values | Align comparable values, use consistent units and tabular numerals where available. Use an em dash plus an explanation for unavailable values, never a fabricated zero. |
| Motion | Brief, purposeful transitions, ordinarily 120–200 ms for interface changes. Keep execution graphs stable. Reduced motion retains every status and result without requiring animated movement. |

Avoid decorative gradients, glass effects, neon glows, unnecessary animated backgrounds, emoji navigation, oversized pill badges, repeated card grids, or unrelated illustrations in the core workspace. Do not copy a component-library example wholesale and call the design complete. Status badges, cards and animation are appropriate when they convey a specific state or relationship.

Light appearance is the initial visual baseline. Dark appearance is optional and must meet the same readability requirements if implemented; a theme toggle is not a v1 release requirement.

## Information hierarchy and density

Use three levels of detail. Preserve discoverability: supplementary information must have an explicit, consistently placed control, not be available only on hover.

| Level | Visible content | Interaction |
| --- | --- | --- |
| Overview | Current question, selected sources/configurations, readiness, lane status, answer, citations and primary elapsed time | Available immediately in the comparison view |
| Explanation | Stage purpose, input/output summaries, selected evidence, retrieval/first-token timing, rank changes and relevant warnings | One labeled tab, row or details action away |
| Technical detail | Full candidate tables, parameters, model metadata, IDs and raw event data | Explicit expandable section in the relevant inspector |

Apply these rules:

- Show concise labels and one short helper sentence where a concept first appears. Put longer explanations in an on-demand explanation panel.
- Display consequential warnings, failure reasons, incomplete evidence and unsupported states at the affected control or result. Do not hide them to achieve a cleaner screenshot.
- Keep each lane's answer as the primary reading area. Place status and total time in a compact header; put the timing breakdown in a consistently discoverable detail view. Queue time stays visible beside the total when relevant.
- Use one shared inspector for the selected lane, stage or source. Do not simultaneously open competing evidence, settings and raw-trace drawers. Replacing inspector content must preserve a clear title and back/close action.
- Keep long answers and full evidence available. An excerpt may be collapsed with an explicit expansion action; never silently truncate the answer or hide a citation.
- Use compact source lists and candidate tables. Show a small initial result preview, ordinarily five rows, with the full count and an action to inspect the rest. Technical tables may scroll locally.
- Keep names, ranks and locations readable. Truncated filenames must have an accessible way to read the full name. Prevent long IDs from stretching the layout.

### Screen-specific priorities

| Screen or region | Primary focus | Secondary information |
| --- | --- | --- |
| Sources | Source list, readiness and upload/import | Parsing warnings and source preview; connector details on request |
| Technique selection | Plain-language purpose, compatibility and selection | Settings summary; advanced parameters in a drawer |
| Comparison | Question and readable answers with citations | Workflow, timing breakdown, settings and export |
| Workflow | Clear stage progression and the selected step | Candidate/evidence detail and raw trace |
| History | Question, date, configurations and terminal state | Full recorded run after opening it |
| Export | What will be included, data-inclusion choice and download | Verification details and runtime provenance |

Show two or three readable lanes on desktop depending on available width. Six lanes must not become six compressed columns. At narrow widths use the lane switcher; preserve the question, lane identity and status. The inspector becomes a full-width view with a return action. The page must not acquire horizontal overflow; an intentionally labeled lane scroller or technical table can scroll within its own region.

## Every simulation step must be understandable

The product may call this a simulation, but its execution view is an explanation of observed events. The visualization never supplies fabricated intermediate data or private model reasoning.

Use a compact step summary in the graph/list and one focused explanation panel. Each selected step uses the same reading order:

| Part | Required content |
| --- | --- |
| Name and state | Short verb-led label, technique context when needed, and pending/running/completed/failed/skipped/cancelled status |
| Purpose | One sentence explaining what the operation does in everyday language |
| Input | A concise description and available count/preview of what entered this step |
| Action and result | What observable operation ran and what changed: ranks, selected pages, expanded text, packed passages or answer text |
| Time and next state | Observed duration, a visible wait/failure explanation when applicable, and the next dependency or downstream stage |

Pending outputs say "Not available yet." A provider's unobserved internal operations say "Not exposed by this provider." Completed, failed and skipped steps must look different. Do not write vague activity labels such as "AI magic" or show a confidence percentage for a native retrieval score.

Use plain-language names with the technical term available alongside or in the description:

| Technical operation | Suggested step label | What the user can inspect |
| --- | --- | --- |
| Lexical search / BM25 | Match query words | Query terms and ranked matching passages |
| Query embedding | Represent the question | Input question, model and vector dimensions; no invented geometric journey |
| Dense search | Find similar passages | Retrieved passages, their order and cosine scores |
| RRF fusion | Combine search results | Branch membership, duplicate handling and fused ranks |
| Reranking | Reorder the candidates | Before/after rank using stable passage identity |
| Parent expansion | Add surrounding context | Child match, linked parent and added source text |
| Tree navigation | Select a document section | Observable node selection and page ranges |
| Context packing | Choose evidence for the answer | Included/excluded passages and the recorded budget decision |
| Generation | Write the answer | Supplied evidence, streaming answer and citations |

Example wording, using fictional values only: "Reorder the candidates — compared 20 passages with the question. Five passages were selected for the next step." Populate counts from the trace; never hardcode example values into a live view. If a reason for selection or omission was not recorded, say so instead of inferring one from the final answer.

## Progression, playback and branches

- Show the whole workflow at a readable overview scale with short labels. Use a selected-step panel to carry the detailed explanation, not paragraphs inside every node.
- Keep the user's inspected step selected while other events arrive. Highlight live running stages separately; an explicit "Follow live" control can restore automatic focus.
- Represent parallel lexical and dense searches as sibling branches with a visible join. Multiple stages may be running at once. Explain that the merge waits for its required branches; do not draw a false serial sequence.
- Preserve stable evidence identity while showing changes. A reranking view aligns the same passage's old and new rank. Parent expansion links the matching child to the added text. Tree navigation shows section titles and actual page ranges.
- Default replay controls are Play/Pause, Previous step, Next step, seek and playback speed. Raw event stepping belongs in technical detail. Apply the presentation-boundary rules in document 07 so this is a view over the existing event stream, not a new execution engine.
- Keep token deltas inside the "Write the answer" step. A rapidly streaming answer must not create hundreds of visible steps or steal keyboard focus.
- Show the useful output of each observed step as soon as it is available. If live execution moves too fast to read, make completed steps inspectable and replayable. Do not delay the backend or conceal a completed answer to pace a lesson.
- Use subtle state transitions and optional connector emphasis to explain movement. Do not require users to track decorative particles or flashing nodes.
- Avoid percentage progress when the remaining work is unknown. Show the current operation, elapsed time and observed counts instead. PageIndex's adaptive route must not display a fictitious fixed total of future steps.
- Playback speed and compressed waits must be visibly labeled. Original measured durations remain available and unchanged.

## Content and state quality

Use consistent nouns: source, corpus, technique, configuration, lane, evidence and step. Introduce specialist terms with a short explanation rather than assuming the user knows them. Error text states what failed and the available next action. Empty states explain the next useful action without decorative filler.

Review loading, streaming, completed, empty, insufficient-evidence, failed, cancelled, disconnected and unavailable states. A polished success screen does not compensate for confusing failure states. Layout and action placement should remain stable as the state changes.

## Design review is a release gate

Implement and manually inspect the states in the U-series acceptance matrix in document 11. Capture representative screenshots and a short replay recording or equivalent frame sequence in IMPLEMENTATION_STATUS.md, recording viewport, state and review result. Review at 1440×900, 1024×768 and 390×844 and at 200% text/browser zoom where applicable.

The reviewer must be able to identify the question, active lane, current operation, result/evidence and next action without opening raw trace data. For each selected step, input, action, result and duration must be understandable from its focused panel. No clipped controls, unreadable lanes, unexplained scores, overlapping overlays or competing visual emphasis may remain.

Automated checks can verify interaction and state behavior; visual maturity and explanation clarity also require inspecting the rendered application. Do not mark this gate passed from schema checks, static mockups or this documentation pack alone.
