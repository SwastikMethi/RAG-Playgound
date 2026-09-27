import { useState } from "react";
import { api, type Lane, type Run } from "./api";
import { Button, ErrorNotice } from "./ui";

export function LaneFeedback({ runId, lane }: { runId: string; lane: Lane }) {
  const [value, setValue] = useState<NonNullable<Lane["feedback"]>>(lane.feedback || { helpful: "unset", note: "" });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  return <details className="lane-details"><summary>Your feedback{value.helpful !== "unset" ? ` · ${value.helpful}` : ""}</summary>
    <form onSubmit={async (e) => {
      e.preventDefault(); setError(""); setMessage("");
      try { await api(`/runs/${runId}/lanes/${lane.id}/feedback`, { method: "PUT", body: JSON.stringify(value) }); setMessage("Feedback saved"); }
      catch (e) { setError((e as Error).message); }
    }}>
      <label>Was this answer useful?<select value={value.helpful} onChange={(e) => setValue({ ...value, helpful: e.target.value as typeof value.helpful })}>
        <option value="unset">Not judged yet</option><option value="helpful">Helpful</option><option value="unhelpful">Unhelpful</option>
      </select></label>
      <label>Answer note<textarea value={value.note} maxLength={2000} onChange={(e) => setValue({ ...value, note: e.target.value })} /></label>
      {error && <ErrorNotice message={error} />}<Button type="submit">Save feedback</Button><span role="status">{message}</span>
    </form>
  </details>;
}

export function RunPreference({ run }: { run: Run }) {
  const preference = run.preference || { preferred_lane_id: null, tied_lane_ids: [], note: "" };
  const [choice, setChoice] = useState(preference.preferred_lane_id || (preference.tied_lane_ids.length ? "tie" : ""));
  const [tied, setTied] = useState(preference.tied_lane_ids);
  const [note, setNote] = useState(preference.note);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  return <details className="comparison-notes"><summary>Your comparison notes</summary>
    <p className="caption">Choose based on the answers and their sources. Timings do not determine an answer’s quality.</p>
    <form onSubmit={async (e) => {
      e.preventDefault(); setError(""); setMessage("");
      if (choice === "tie" && tied.length < 2) { setError("Select at least two lanes for a tie."); return; }
      try { await api(`/runs/${run.id}/preference`, { method: "PUT", body: JSON.stringify({ preferred_lane_id: choice && choice !== "tie" ? choice : null, tied_lane_ids: choice === "tie" ? tied : [], note }) }); setMessage("Comparison note saved"); }
      catch (e) { setError((e as Error).message); }
    }}>
      <label>Preferred answer<select value={choice} onChange={(e) => setChoice(e.target.value)}>
        <option value="">No preference</option>{run.lanes.map((lane, i) => <option value={lane.id} key={lane.id}>Lane {i + 1} · {lane.technique}</option>)}
        {run.lanes.length > 1 && <option value="tie">Tie between lanes</option>}
      </select></label>
      {choice === "tie" && run.lanes.map((lane, i) => <label className="inline-check" key={lane.id}><input type="checkbox" checked={tied.includes(lane.id)} onChange={(e) => setTied(e.target.checked ? [...tied, lane.id] : tied.filter((id) => id !== lane.id))} /> Lane {i + 1} · {lane.technique}</label>)}
      <label>Comparison note<textarea value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} /></label>
      {error && <ErrorNotice message={error} />}<Button type="submit">Save comparison note</Button><span role="status">{message}</span>
    </form>
  </details>;
}
