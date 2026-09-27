import { describe, it, expect } from "vitest";
import { reduceEvent, emptyState, type TraceEvent } from "./reducer";

const event = (
  seq: number,
  type: string,
  payload: Record<string, unknown>,
  lane_id: string | null = "lane",
): TraceEvent =>
  ({
    schema_version: "1.0.0",
    event_id: `run:${seq}`,
    run_id: "run",
    seq,
    elapsed_ms: seq,
    emitted_at: "2026-09-26T00:00:00Z",
    type,
    lane_id,
    payload,
  }) as TraceEvent;
describe("the live and replay reducer", () => {
  it("ignores duplicate frames, preserves Unicode offsets, and stops on a sequence gap", async () => {
    let state = emptyState("run");
    const frames = [
      event(1, "run.started", { lane_ids: ["lane"], queue_ms: 5 }, null),
      event(2, "lane.started", {}),
      event(3, "answer.delta", { offset_chars: 0, text: "A🪐" }),
      event(4, "answer.delta", { offset_chars: 2, text: "B" }),
    ];
    for (const frame of frames) state = await reduceEvent(state, frame);
    expect(state.lanes.lane.answer).toBe("A🪐B");
    expect(await reduceEvent(state, frames[2])).toBe(state);
    expect(
      (
        await reduceEvent(
          state,
          event(6, "answer.delta", { offset_chars: 3, text: "X" }),
        )
      ).resync,
    ).toBe(true);
    expect(
      (
        await reduceEvent(
          state,
          event(5, "answer.delta", { offset_chars: 4, text: "X" }),
        )
      ).lanes.lane.answer,
    ).toBe("A🪐B");
    let reloaded = emptyState("run");
    for (const frame of frames) reloaded = await reduceEvent(reloaded, frame);
    expect(reloaded).toEqual(state);
  });
});

it("verifies citation labels as well as hashes and rebuilds earlier replay state", async () => {
  const { replay } = await import("./reducer");
  const text = "A🪐 [E1] [E9]";
  const hash = Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)),
    ),
    (x) => x.toString(16).padStart(2, "0"),
  ).join("");
  const frames = [
    event(1, "run.started", { lane_ids: ["lane"], queue_ms: 0 }, null),
    event(2, "lane.started", {}),
    event(3, "stage.started", { span_id: "pack", stage: "context_packing", parent_span_id: null }),
    event(4, "context.selected", { span_id: "pack", evidence: [{ label: "E1" }], token_count: 4, budget_tokens: 10, token_count_kind: "exact", excluded_candidate_ids: [] }),
    event(5, "answer.delta", { offset_chars: 0, text }),
    event(6, "answer.completed", {
      text_sha256: hash,
      valid_citation_labels: ["E1"],
      invalid_citation_labels: ["E9"],
    }),
    event(7, "lane.completed", { metrics: { total_ms: 6 } }),
    event(8, "run.completed", { status: "completed" }, null),
  ];
  const final = await replay("run", frames);
  expect(final.resync).toBe(false);
  expect((await replay("run", frames, 3)).lanes.lane.answer).toBe("");
  const bad = await reduceEvent(
    await replay("run", frames, 5),
    event(6, "answer.completed", {
      text_sha256: hash,
      valid_citation_labels: ["E9"],
      invalid_citation_labels: [],
    }),
  );
  expect(bad.resync).toBe(true);
  expect(
    (
      await reduceEvent(
        final,
        event(9, "answer.delta", { offset_chars: 13, text: "late" }),
      )
    ).resync,
  ).toBe(true);
});

it("preserves a queued cancellation when the other lane starts and completes", async () => {
  const { replay } = await import("./reducer");
  const result = await replay("run", [
    event(1, "lane.cancelled", { metrics: null }),
    event(2, "run.started", { lane_ids: ["lane", "other"], queue_ms: 0 }, null),
    event(3, "lane.started", {}, "other"),
    event(4, "lane.completed", { metrics: { total_ms: 1 } }, "other"),
    event(5, "run.completed", { status: "partial" }, null),
  ]);
  expect(result.resync).toBe(false);
  expect(result.lanes.lane.status).toBe("cancelled");
  expect(result.lanes.lane.metrics).toBeNull();
  expect(result.lanes.other.status).toBe("completed");
});

it("preserves and explains the recorded context packing decision", async () => {
  const { replay } = await import("./reducer");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const { createElement } = await import("react");
  const { StepInspector } = await import("./Workflow");
  const evidence = [{ candidate_id: "chosen", evidence_id: "chosen", label: "E1", rank: 1, source_name: "guide.md", excerpt: "Exact supplied text", score: 0.8, score_type: "cosine" }];
  const result = await replay("run", [
    event(1, "run.started", { lane_ids: ["lane"] }, null),
    event(2, "stage.started", { span_id: "pack", stage: "context_packing", parent_span_id: null }),
    event(3, "context.selected", { span_id: "pack", evidence, token_count: 17, budget_tokens: 256, token_count_kind: "exact", excluded_candidate_ids: ["omitted"] }),
    event(4, "stage.completed", { span_id: "pack", duration_ms: 4, details: { output_count: 1 } }),
  ]);
  const step = result.lanes.lane.stages.pack;
  expect(step.details.token_count).toBe(17);
  expect(step.details.budget_tokens).toBe(256);
  expect(step.details.excluded_candidate_ids).toEqual(["omitted"]);
  expect(step.candidates).toEqual(evidence);
  const html = renderToStaticMarkup(createElement(StepInspector, { runId: "run", laneId: "lane", step, onEvidence: () => {} }));
  expect(html).toContain("17 of 256 context tokens used");
  expect(html).toContain("1 candidate excluded");
  expect(html).toContain("Exact supplied text");
});
