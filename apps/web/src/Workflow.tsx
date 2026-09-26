import { useEffect, useMemo, useState } from "react";
import {
  Handle,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Check, Clock3, Info } from "lucide-react";
import { api } from "./api";
import { Button, ErrorNotice, Status } from "./ui";
import type { Evidence, LaneState, Stage } from "./reducer";

export const duration = (n: number | null | undefined) =>
  n == null
    ? "Not measured"
    : n < 1000
      ? `${Math.round(n)} ms`
      : `${(n / 1000).toFixed(2)} s`;
const steps: Record<
  string,
  {
    label: string;
    purpose: string;
    input: string;
    action: string;
    next: string;
  }
> = {
  retrieval: {
    label: "Retrieve evidence",
    purpose: "Find source material that may answer this question.",
    input: "The question and this prepared corpus.",
    action: "Coordinates the retrieval steps shown below.",
    next: "Pack the selected evidence.",
  },
  lexical_search: {
    label: "Keyword search",
    purpose: "Find passages sharing meaningful words with the question.",
    input: "Question terms and the prepared BM25 index.",
    action: "BM25 scores only passages containing at least one question term.",
    next: "Combine ranks or pack evidence.",
  },
  query_embedding: {
    label: "Embed question",
    purpose: "Represent the question in the same vector space as the passages.",
    input: "The original question and configured embedding model.",
    action:
      "Requests one query vector for this lane; other lanes do their own query embedding.",
    next: "Search this corpus’s vectors.",
  },
  dense_search: {
    label: "Semantic search",
    purpose: "Find passages whose vectors are similar to the question vector.",
    input: "The question vector and this corpus/index namespace.",
    action: "Qdrant ranks scoped passages using cosine similarity.",
    next: "Combine ranks, expand parents or pack evidence.",
  },
  fusion: {
    label: "Combine ranks",
    purpose: "Bring keyword and semantic candidates into one list.",
    input: "The two completed branch rankings.",
    action: "Equal reciprocal rank fusion combines positions, not raw scores.",
    next: "Rerank or pack the fused candidates.",
  },
  rerank: {
    label: "Rerank passages",
    purpose: "Score candidate passages directly against the original question.",
    input: "The fused candidates and local cross-encoder.",
    action:
      "The pinned English model scores a bounded question/passage window. Source excerpts remain unchanged.",
    next: "Pack the highest-ranked passages.",
  },
  parent_expansion: {
    label: "Expand parents",
    purpose: "Add surrounding context to small retrieved passages.",
    input: "Retrieved children and their recorded parent links.",
    action:
      "Collects each parent once, preserving the best child order and source boundaries.",
    next: "Pack parents within the shared context budget.",
  },
  document_selection: {
    label: "Select documents",
    purpose: "Narrow the PDF corpus before navigating its section trees.",
    input: "The question and bounded document descriptors.",
    action:
      "Selects valid document IDs; a single document is selected without a model call.",
    next: "Navigate selected document trees.",
  },
  tree_navigation: {
    label: "Navigate sections",
    purpose:
      "Select relevant original PDF pages through their section structure.",
    input: "Only the current bounded node descriptors and question.",
    action:
      "Validates selected node IDs and follows recorded page mappings within the configured limits.",
    next: "Pack selected page text.",
  },
  context_packing: {
    label: "Pack evidence",
    purpose: "Give every technique the same finite evidence budget.",
    input: "The ranked candidates and context/output token limits.",
    action:
      "Deduplicates overlapping spans, labels passages and clips exact spans when needed.",
    next: "Generate from these passages, or report insufficient evidence.",
  },
  generation: {
    label: "Write answer",
    purpose: "Answer using the selected source evidence.",
    input: "The shared grounded-answer prompt, question and labeled evidence.",
    action:
      "Streams the answer and checks citation labels. It does not verify source correctness.",
    next: "Inspect the cited sources and judge the answer.",
  },
};

type StepNode = Node<
  { name: string; step?: Stage; select: () => void },
  "step"
>;
function StepNodeView({ data }: NodeProps<StepNode>) {
  return (
    <button
      tabIndex={-1}
      className={`workflow-node ${data.step?.status || "pending"}`}
      onClick={data.select}
    >
      <Handle type="target" position={Position.Top} />
      <strong>{steps[data.name]?.label || data.name}</strong>
      <span>
        <Status value={data.step?.status || "pending"} />
        <span>
          {data.step?.duration != null ? duration(data.step.duration) : ""}
        </span>
      </span>
      <Handle type="source" position={Position.Bottom} />
    </button>
  );
}
const nodeTypes = { step: StepNodeView };

export function Workflow({
  technique,
  state,
  selected,
  follow,
  onFollow,
  onSelect,
}: {
  technique: string;
  state?: LaneState;
  selected?: string;
  follow: boolean;
  onFollow: () => void;
  onSelect: (id: string) => void;
}) {
  const [reduceMotion, setReduceMotion] = useState(
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const q = matchMedia("(prefers-reduced-motion: reduce)");
    const change = () => setReduceMotion(q.matches);
    q.addEventListener("change", change);
    return () => q.removeEventListener("change", change);
  }, []);
  const records = Object.values(state?.stages || {});
  const { nodes, edges, height } = useMemo(() => {
    const layout: { name: string; x: number; y: number }[] = [];
    const pairs: string[][] = [];
    const add = (name: string, x: number, y: number) =>
      layout.push({ name, x, y });
    let last = "",
      row = 0;
    if (technique === "bm25") {
      add("lexical_search", 110, 0);
      last = "lexical_search";
      row = 100;
    } else if (technique === "pageindex") {
      add("document_selection", 110, 0);
      add("tree_navigation", 110, 100);
      pairs.push(["document_selection", "tree_navigation"]);
      last = "tree_navigation";
      row = 200;
    } else if (technique.startsWith("hybrid")) {
      add("lexical_search", 0, 100);
      add("query_embedding", 220, 0);
      add("dense_search", 220, 100);
      add("fusion", 110, 200);
      pairs.push(
        ["query_embedding", "dense_search"],
        ["lexical_search", "fusion"],
        ["dense_search", "fusion"],
      );
      last = "fusion";
      row = 300;
    } else {
      add("query_embedding", 110, 0);
      add("dense_search", 110, 100);
      pairs.push(["query_embedding", "dense_search"]);
      last = "dense_search";
      row = 200;
    }
    for (const name of [
      ...(technique === "hybrid_rerank"
        ? ["rerank"]
        : technique === "parent_child"
          ? ["parent_expansion"]
          : []),
      "context_packing",
      "generation",
    ]) {
      add(name, 110, row);
      pairs.push([last, name]);
      last = name;
      row += 100;
    }
    const current = Object.fromEntries(
      records.map((step) => [step.name, step]),
    );
    return {
      height: Math.min(560, row + 40),
      nodes: layout.map(({ name, x, y }) => ({
        id: name,
        type: "step",
        position: { x, y },
        data: {
          name,
          step: current[name],
          select: () => {
            if (current[name]) onSelect(current[name].id);
          },
        },
        selected: current[name]?.id === selected,
      })),
      edges: pairs.map(([source, target]) => ({
        id: `${source}-${target}`,
        source,
        target,
        type: "smoothstep",
        animated: !reduceMotion && current[target]?.status === "running",
        style: {
          stroke:
            current[source]?.status === "completed" ? "#3c958b" : "#c5d1d7",
          strokeWidth: 1.5,
        },
      })),
    };
  }, [
    technique,
    records.map((s) => `${s.id}:${s.status}:${s.duration}`).join("|"),
    selected,
    reduceMotion,
    onSelect,
  ]);
  return (
    <section className="workflow">
      <div className="workflow-caption">
        <span className="caption">
          Recorded operations · no private model reasoning
        </span>
        <Button aria-pressed={follow} onClick={onFollow}>
          {follow ? <Check size={14} /> : <Clock3 size={14} />}Follow live
        </Button>
      </div>
      <div style={{ height }} aria-hidden="true">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          elementsSelectable={false}
          zoomOnScroll={false}
          panOnScroll={false}
          proOptions={{ hideAttribution: true }}
          minZoom={0.25}
          maxZoom={1}
        />
      </div>
      <ol className="step-list" aria-label="Recorded execution steps">
        {records.map((step) => (
          <li key={step.id}>
            <button
              aria-pressed={step.id === selected}
              onClick={() => onSelect(step.id)}
            >
              <span>{steps[step.name]?.label || step.name}</span>
              <Status value={step.status} />
              <span className="caption">{duration(step.duration)}</span>
            </button>
          </li>
        ))}
      </ol>
      {!records.length && (
        <p className="caption">
          Steps will activate only when execution events arrive.
        </p>
      )}
    </section>
  );
}

export function StepInspector({
  runId,
  laneId,
  step,
  onEvidence,
}: {
  runId: string;
  laneId: string;
  step?: Stage;
  onEvidence: (e: Evidence) => void;
}) {
  const [full, setFull] = useState<null | Record<string, unknown>>(null),
    [error, setError] = useState("");
  useEffect(() => {
    setFull(null);
    setError("");
  }, [step?.id]);
  if (!step)
    return (
      <p className="muted">
        This step has not started at the selected replay position.
      </p>
    );
  const description = steps[step.name];
  const candidates =
    (full?.payload as { candidates?: Evidence[] } | undefined)?.candidates ||
    step.candidates;
  return (
    <>
      <div className="step-title">
        <h3>{description?.label || step.name}</h3>
        <Status value={step.status} />
      </div>
      <div className="step-explanation">
        <h4>Purpose</h4>
        <p>{description?.purpose}</p>
        <h4>Input</h4>
        <p>{description?.input}</p>
        {step.details.input_count != null && (
          <p className="caption">
            {String(step.details.input_count)} input items
          </p>
        )}
        {Array.isArray(step.details.query_terms) && (
          <div className="term-list">
            {step.details.query_terms.map((term, i) => (
              <span key={i}>{String(term)}</span>
            ))}
          </div>
        )}
        {Boolean(step.details.model) && (
          <p className="caption">Model: {String(step.details.model)}</p>
        )}
        <h4>Action and result</h4>
        <p>{description?.action}</p>
        {step.status === "running" ? (
          <p className="muted">Running. Results have not been recorded yet.</p>
        ) : step.status === "skipped" ? (
          <p>{String(step.details.summary)}</p>
        ) : (
          <>
            {step.details.output_count != null && (
              <p>
                <strong>{String(step.details.output_count)}</strong> output
                items recorded.
              </p>
            )}
            {Boolean(step.details.summary) && (
              <p className="caption">{String(step.details.summary)}</p>
            )}
          </>
        )}
        {step.error && <ErrorNotice message={step.error} />}
        <h4>Measured duration</h4>
        <p>{duration(step.duration)}</p>
        <h4>Next dependency</h4>
        <p>{description?.next}</p>
      </div>
      {candidates.length > 0 && (
        <>
          <h3 className="spaced">Recorded candidates</h3>
          <ol className="candidate-list">
            {candidates.map((item) => (
              <li key={item.candidate_id}>
                <button onClick={() => onEvidence(item)}>
                  <strong>
                    #{item.rank} · {item.source_name}
                  </strong>
                  <span className="caption">
                    {item.score_type} {item.score?.toFixed(4)}
                    {item.branch_ranks?.lexical
                      ? ` · keyword #${item.branch_ranks.lexical}`
                      : ""}
                    {item.branch_ranks?.dense
                      ? ` · semantic #${item.branch_ranks.dense}`
                      : ""}
                  </span>
                  <span>
                    {item.excerpt.slice(0, 220)}
                    {item.excerpt.length > 220 ? "…" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
      {step.selections.length > 0 && (
        <>
          <h3 className="spaced">Selected sections</h3>
          {step.selections.map((node, i) => (
            <p key={i}>
              {String(node.title || node.node_id)}{" "}
              <span className="caption">
                pages {String(node.page_start)}–{String(node.page_end)}
              </span>
            </p>
          ))}
        </>
      )}
      {Array.isArray(step.details.changes) && (
        <>
          <h3 className="spaced">Rank changes</h3>
          <table className="rank-table">
            <thead>
              <tr>
                <th>Before</th>
                <th>After</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {(
                step.details.changes as {
                  before_rank: number;
                  after_rank: number;
                  score: number;
                }[]
              ).map((c, i) => (
                <tr key={i}>
                  <td>{c.before_rank}</td>
                  <td>{c.after_rank}</td>
                  <td>{c.score.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {typeof step.details.artifact_id === "string" && !full && (
        <Button
          onClick={() =>
            api<{ data: Record<string, unknown> }>(
              `/runs/${runId}/lanes/${laneId}/artifacts/${step.details.artifact_id}`,
            )
              .then((r) => setFull(r.data))
              .catch((e) => setError(e.message))
          }
        >
          <Info size={16} />
          Load full recorded detail
        </Button>
      )}
      {error && <ErrorNotice message={error} />}
    </>
  );
}

export function LiveDuration({
  state,
  elapsed,
  connected,
  replaying,
}: {
  state?: LaneState;
  elapsed: number;
  connected: boolean;
  replaying: boolean;
}) {
  const [extra, setExtra] = useState(0);
  useEffect(() => {
    setExtra(0);
    if (!connected || replaying || state?.status !== "running") return;
    const start = performance.now();
    const timer = setInterval(() => setExtra(performance.now() - start), 100);
    return () => clearInterval(timer);
  }, [elapsed, connected, replaying, state?.status]);
  const final = state?.metrics?.total_ms;
  const observed =
    state?.started != null ? Math.max(0, elapsed - state.started) : null;
  return (
    <strong
      title={
        final != null
          ? "Measured by the worker"
          : "Live display estimate; freezes when disconnected."
      }
    >
      {duration(final ?? (observed == null ? null : observed + extra))}
    </strong>
  );
}
