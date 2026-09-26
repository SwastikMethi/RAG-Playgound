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
