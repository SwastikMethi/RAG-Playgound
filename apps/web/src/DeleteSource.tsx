import { useEffect, useState } from "react";
import type { components } from "./generated/api";
import { api, type Job, type Source } from "./api";
import { Button, ErrorNotice } from "./ui";

export function DeleteSource({ source, onDeleted }: { source: Source; onDeleted: () => Promise<void> }) {
  const [impact, setImpact] = useState<components["schemas"]["SourceImpact"] | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<typeof impact>(`/sources/${source.id}/impact`).then(setImpact).catch((e) => setError(e.message)); }, [source.id]);
  async function remove() {
    setBusy(true); setError("");
    try {
      const result = await api<{ job_id: string }>(`/sources/${source.id}?cascade=true&confirmation_source_id=${encodeURIComponent(source.id)}`, { method: "DELETE" });
      let job: Job;
      do { await new Promise((resolve) => setTimeout(resolve, 600)); job = await api<Job>(`/jobs/${result.job_id}`); } while (["queued", "running"].includes(job.status));
      if (job.status !== "succeeded") throw new Error(job.error?.message || "Cleanup did not finish. Retry this deletion after checking service readiness.");
      await onDeleted();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <>
    <h3>{source.display_name}</h3>
    <p>Deletion removes the source and comparisons that depend on it.</p>
    {impact && <dl><dt>Corpus versions</dt><dd>{impact.corpus_count}</dd><dt>Prepared indexes</dt><dd>{impact.bundle_count}</dd><dt>Saved comparisons</dt><dd>{impact.run_count}</dd><dt>Stored exports</dt><dd>{impact.export_count}</dd></dl>}
    <p className="caption">Raw files, captured rows, extracted text, vectors, traces and stored downloads are removed. Copies you already downloaded cannot be revoked. Unrelated sources are kept.</p>
    {!!impact?.active_job_ids.length && <ErrorNotice message="Stop active source, preparation, comparison or export jobs before deleting. Close and reopen this panel to refresh the impact." />}
    <label className="inline-check"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={busy} /> Delete this source and all listed dependent content</label>
    {error && <ErrorNotice message={error} />}
    <div className="form-actions"><Button tone="danger" loading={busy} onClick={remove} disabled={!confirmed || !impact || !!impact.active_job_ids.length || busy}>{source.status === "deleting" ? "Retry cleanup" : "Delete source permanently"}</Button></div>
    <p className="caption" role="status">{busy ? "Confirmed cleanup continues if this panel is closed." : ""}</p>
  </>;
}
