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
    event(3, "context.selected", { evidence: [{ label: "E1" }] }),
    event(4, "answer.delta", { offset_chars: 0, text }),
    event(5, "answer.completed", {
      text_sha256: hash,
      valid_citation_labels: ["E1"],
      invalid_citation_labels: ["E9"],
    }),
    event(6, "lane.completed", { metrics: { total_ms: 6 } }),
    event(7, "run.completed", { status: "completed" }, null),
  ];
  const final = await replay("run", frames);
  expect(final.resync).toBe(false);
  expect((await replay("run", frames, 3)).lanes.lane.answer).toBe("");
  const bad = await reduceEvent(
    await replay("run", frames, 4),
    event(5, "answer.completed", {
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
        event(8, "answer.delta", { offset_chars: 13, text: "late" }),
      )
    ).resync,
  ).toBe(true);
});
