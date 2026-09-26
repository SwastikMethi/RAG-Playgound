# Timing and replay semantics

## What the timers measure

Each comparison is an observed execution under its disclosed settings and resource contention. Do not label a fastest response the best-quality approach or extrapolate one run into a production latency claim.

Use monotonic server clocks for elapsed durations. UTC wall timestamps are for ordering across resources and display. One compare coordinator owns the run timing origin and receives stage events from its lane tasks.

| Metric | Exact definition |
| --- | --- |
| preparation_ms | Work performed by the preparation job; separate from question execution |
| preparation_reused | Whether a ready artifact set was reused; preserve its original build metadata |
| queue_ms | API acceptance to compare-job start, measured using the same PostgreSQL time source |
| retrieval_ms | Wall duration of the lane's retrieval span, including embedding, search, fusion, reranking or tree selection and their waits |
| context_ms | Duration of evidence deduplication, source mapping, labeling and budget packing |
| generation_ms | Generation-stage start through stream completion, including admission wait, provider time and permitted retries |
| ttft_ms | lane.started to the first nonempty final-answer text delta received from the answer provider |
| total_ms | lane.started to the lane's terminal transition, including retrieval, context, generation and finalization |
| provider_wait_ms | Sum of explicit provider-admission waits; diagnostic only and may overlap across parallel branches |

Neither preparation nor run queue time is hidden inside the primary query total. Display queue_ms next to total where relevant. The total can exceed the sum of the main stage metrics because finalization and event persistence take time. Parallel stage durations must not be summed and presented as wall latency.

For PageIndex, internal selection-model output is not the first answer token. Only final answer generation sets TTFT. For insufficient-evidence responses, TTFT and generation_ms are null and generation is recorded as skipped.

A failed or cancelled stage preserves measured elapsed time and partial output. Missing metrics are null, never zero. A queued lane cancelled before it starts has null total_ms. A run accepted but not yet claimed has an observable waiting status; no live query clock starts.

## Instrumentation rules

- Capture stage start before resource admission so observed waits are included.
- Capture first-answer text arrival immediately, before buffering or database writes.
- Every started span must eventually terminate as completed or failed, or be closed as cancelled in terminal lane metadata. Emit a stage.failed with CANCELLED for active spans during cancellation.
- completed stage duration cannot be negative. Terminal total must be at least every nonoverlapping phase duration and TTFT when present.
- Record retry counts and wait durations; do not subtract them to improve a displayed number.
- Do not include animation delay, browser rendering or replay speed in server metrics.
- Treat different prompt/output lengths and warm model/index state as visible context, not hidden normalization.

Keep answer caching disabled in v1. Index and loaded-model reuse are permitted and disclosed. No shared query-embedding result is handed to a lane without measuring and reporting that policy; v1 uses independent query embedding per lane.

## Replay reducer

Implement one pure reducer from ordered events to run state. The live UI and replay UI share it. Given the same event sequence, they must produce identical lane answers, terminal statuses, citations, candidate ranking state and metrics.

Rules:

1. Ignore an event with seq <= last_applied_seq after checking the event belongs to the run.
2. If a gap is detected, pause application of later frames and refetch from the last contiguous sequence. Do not invent missing transitions.
3. answer.delta has offset_chars equal to the current answer's Unicode code-point count. A mismatch triggers resynchronization. JavaScript UTF-16 string length alone is not sufficient.
4. stage lifecycle is keyed by span_id, not just stage name. Parallel and repeated stages coexist.
5. Candidate lists replace the corresponding recorded stage result; they are not blindly appended on reconnect.
6. answer.completed validates the concatenated text hash and citation labels.
7. A terminal lane cannot return to running. A terminal run cannot accept new lane output.

Save replay cursor and speed locally as presentation state. They do not modify server trace content. Backward stepping rebuilds from the prefix or a verified checkpoint. A checkpoint includes its last sequence and is invalidated if its hash does not match the event prefix.

## Teaching mode

Provide normal playback at recorded spacing and an optional compressed-gap playback. Compressed mode can shorten long waits to keep an explanation understandable; its badge and time ruler retain the actual server durations.

If recorded execution is too fast to see, users can step through events. Do not artificially sleep in the backend or change a measured duration to make the animation impressive.

## Clear presentation steps

Default Previous step and Next step controls navigate meaningful recorded transitions. Build their boundaries from stage.started, stage.completed, stage.failed, stage.skipped, and lane/run terminal events. Surface recorded warnings at their original sequence; a warning that changes the user's interpretation can also be a visible stop. Group span events by span_id so repeated tree visits and parallel search branches retain distinct identities.

Moving to a boundary applies every intervening event through the existing reducer in global sequence order. Moving backward rebuilds the corresponding prefix. Candidate, ranking and page-selection outputs remain attached to their actual span and become visible at their recorded point. Answer deltas remain within the generation step and do not each create another visible step. Raw-event stepping stays available in technical detail.

The stepper is a presentation projection over the stored trace; it adds no backend waits, provider calls or fabricated events and requires no new wire schema. Global event order does not imply that parallel stages ran serially. Multiple active branches remain visible, and no fixed count of future steps is invented for adaptive tree navigation.

Each selected step explains purpose, input, observed action/result and duration in the format defined in document 13. Keep the inspected step stable during live updates until the user chooses another step or enables Follow live. During replay, clearly separate the currently inspected recorded state from the actual live execution state.

## Validation

Use a fake monotonic clock for deterministic timing-unit tests. Use integration tests with deliberately delayed branches to prove parallel retrieval wall time reflects the longer branch plus overhead rather than the sum. Use real clocks only for broad operational assertions with generous tolerance.

Include emoji or non-BMP characters in a streaming test, duplicate SSE delivery, interrupted generation, cancellation before start, cancellation during tree selection, and replay after a browser reload.
