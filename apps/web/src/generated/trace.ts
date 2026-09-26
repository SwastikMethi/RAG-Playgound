/* Generated from contracts/trace-event.schema.json. */

export type RAGPlaygroundTraceEvent = {
  schema_version: "1.0.0";
  event_id: string;
  run_id: string;
  lane_id: string | null;
  seq: number;
  emitted_at: string;
  elapsed_ms: number;
  type:
    | "run.started"
    | "lane.started"
    | "stage.started"
    | "stage.completed"
    | "stage.failed"
    | "stage.skipped"
    | "retrieval.candidates"
    | "rerank.completed"
    | "tree.nodes_selected"
    | "context.selected"
    | "answer.delta"
    | "answer.completed"
    | "usage.recorded"
    | "warning"
    | "lane.completed"
    | "lane.failed"
    | "lane.cancelled"
    | "lane.timed_out"
    | "run.completed"
    | "run.partial"
    | "run.failed"
    | "run.cancelled";
  payload: {
    [k: string]: unknown;
  };
};
