import type { RAGPlaygroundTraceEvent } from "./generated/trace";
import type { components } from "./generated/api";
export type TraceEvent = RAGPlaygroundTraceEvent;
export type Evidence =
  components["schemas"]["EvidenceList"]["evidence"][number];
export type Stage = {
  id: string;
  name: string;
  status: string;
  started: number;
  duration: number | null;
  details: Record<string, unknown>;
  candidates: Evidence[];
  selections: Record<string, unknown>[];
  error?: string;
  parent: string | null;
};
export type LaneState = {
  status: string;
  answer: string;
  evidence: Evidence[];
  stages: Record<string, Stage>;
  metrics: components["schemas"]["Timing"] | null;
  warnings: string[];
  error: string | null;
  started: number | null;
};
export type Playback = {
  runId: string;
  lastSeq: number;
  status: string;
  queueMs: number | null;
  lanes: Record<string, LaneState>;
  resync: boolean;
};
export const terminal = (status: string) =>
  ["completed", "partial", "failed", "cancelled", "timed_out"].includes(status);
export function emptyState(runId: string): Playback {
  return { runId, lastSeq: 0, status: "queued", queueMs: null, lanes: {}, resync: false };
}
const emptyLane = (): LaneState => ({
  status: "queued",
  answer: "",
  evidence: [],
  stages: {},
  metrics: null,
  warnings: [],
  error: null,
  started: null,
});
const resync = (state: Playback) => ({ ...state, resync: true });

// Deterministic: Web Crypto checks recorded text, with no network, clock or UI state.
export async function reduceEvent(
  state: Playback,
  event: TraceEvent,
): Promise<Playback> {
  if (event.run_id !== state.runId) return state;
  if (event.seq <= state.lastSeq) return state;
  if (state.resync || event.seq !== state.lastSeq + 1 || terminal(state.status))
    return resync(state);
  const p = event.payload;
  const next: Playback = {
    ...state,
    lastSeq: event.seq,
    lanes: { ...state.lanes },
  };
  if (event.type === "run.started") {
    next.status = "running";
    next.queueMs = typeof p.queue_ms === "number" ? p.queue_ms : null;
    for (const id of p.lane_ids as string[]) next.lanes[id] ??= emptyLane();
  } else if (event.type.startsWith("run.")) next.status = String(p.status);
  if (event.lane_id) {
    const previous = state.lanes[event.lane_id] || emptyLane();
    if (terminal(previous.status)) return resync(state);
    const lane = { ...previous, stages: { ...previous.stages } };
    next.lanes[event.lane_id] = lane;
    if (event.type === "lane.started") {
      lane.status = "running";
      lane.started = event.elapsed_ms;
    } else if (event.type.startsWith("lane.")) {
      lane.status = event.type.slice(5);
      lane.metrics = p.metrics as LaneState["metrics"];
      lane.error =
        (p.error as { message: string } | undefined)?.message || null;
    } else if (event.type === "answer.delta") {
      if (
        p.offset_chars !== Array.from(lane.answer).length ||
        typeof p.text !== "string"
      )
        return resync(state);
      lane.answer += p.text;
    } else if (event.type === "answer.completed") {
      const hash = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(lane.answer),
      );
      const hex = Array.from(new Uint8Array(hash), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
      if (hex !== p.text_sha256) return resync(state);
      const labels = [
        ...new Set(
          Array.from(lane.answer.matchAll(/\[(E[1-9][0-9]*)\]/g), (m) => m[1]),
        ),
      ].sort();
      const known = new Set(lane.evidence.map((e) => e.label));
      if (
        JSON.stringify(labels.filter((l) => known.has(l))) !==
          JSON.stringify(p.valid_citation_labels) ||
        JSON.stringify(labels.filter((l) => !known.has(l))) !==
          JSON.stringify(p.invalid_citation_labels)
      )
        return resync(state);
    } else if (event.type === "warning")
      lane.warnings = [...lane.warnings, String(p.message)];
    else if (event.type === "stage.started") {
      lane.stages[String(p.span_id)] = {
        id: String(p.span_id),
        name: String(p.stage),
        status: "running",
        started: event.elapsed_ms,
        duration: null,
        details: (p.details || {}) as Record<string, unknown>,
        candidates: [],
        selections: [],
        parent: p.parent_span_id as string | null,
      };
    } else if (event.type === "stage.skipped") {
      lane.stages[String(p.span_id)] = {
        id: String(p.span_id),
        name: String(p.stage),
        status: "skipped",
        started: event.elapsed_ms,
        duration: null,
        details: { summary: p.reason },
        candidates: [],
        selections: [],
        parent: null,
      };
    } else if (
      event.type.startsWith("stage.") ||
      [
        "retrieval.candidates",
        "tree.nodes_selected",
        "rerank.completed",
        "context.selected",
      ].includes(event.type)
    ) {
      const prior = lane.stages[String(p.span_id)];
      if (!prior) return resync(state);
      const stage = {
        ...prior,
        details: {
          ...prior.details,
          ...((p.details as Record<string, unknown>) || {}),
        },
      };
      lane.stages[stage.id] = stage;
      if (event.type === "context.selected") {
        lane.evidence = p.evidence as Evidence[];
        stage.candidates = lane.evidence;
        stage.details = { ...stage.details, token_count: p.token_count, token_count_kind: p.token_count_kind, budget_tokens: p.budget_tokens, excluded_candidate_ids: p.excluded_candidate_ids };
      }
      if (event.type === "retrieval.candidates")
        stage.candidates = p.candidates as Evidence[];
      if (event.type === "tree.nodes_selected")
        stage.selections = p.selections as Record<string, unknown>[];
      if (event.type === "rerank.completed") stage.details.changes = p.changes;
      if (event.type === "stage.completed") {
        stage.status = "completed";
        stage.duration = p.duration_ms as number;
      }
      if (event.type === "stage.failed") {
        stage.status =
          (p.error as { code: string }).code === "CANCELLED"
            ? "cancelled"
            : "failed";
        stage.duration = p.duration_ms as number | null;
        stage.error = (p.error as { message: string }).message;
      }
    }
  }
  return next;
}

export async function replay(
  runId: string,
  events: TraceEvent[],
  seq = Infinity,
) {
  let state = emptyState(runId);
  for (const event of events) {
    if (event.seq > seq) break;
    state = await reduceEvent(state, event);
  }
  return state;
}
