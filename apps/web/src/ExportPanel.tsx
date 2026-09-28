import { useEffect, useState } from "react";
import { api, post, downloadFile, type Lane } from "./api";
import type { components } from "./generated/api";
import { Button, ErrorNotice, Status } from "./ui";
type Export = components["schemas"]["Export"];

export function ExportPanel({ runId, lane, fixture }: { runId: string; lane: Lane; fixture: boolean }) {
  const [includeData, setIncludeData] = useState(false);
  const [live, setLive] = useState(false);
  const [item, setItem] = useState<Export | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!item || !["queued", "building"].includes(item.status)) return;
    const timer = setInterval(() => {
      api<Export>(`/exports/${item.id}`).then(setItem).catch((e) => setError(e.message));
    }, 1000);
    return () => clearInterval(timer);
  }, [item?.id, item?.status]);
  async function build() {
    setError(""); setBusy(true);
    try {
      setItem(await post<Export>(`/runs/${runId}/lanes/${lane.id}/exports`, {
        include_data: includeData, verification_mode: live ? "live" : "offline",
      }, true));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function download() {
    if (!item?.download_url) return;
    setError(""); setBusy(true);
    try {
      await downloadFile(item.download_url, "rag-implementation.zip");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const working = busy || !!item && ["queued", "building"].includes(item.status);
  return <>
    <h3>Take this pipeline with you</h3>
    <p className="caption">Download a standalone Python application with this pipeline’s settings, shared runtime, dependency lock and setup commands.</p>
    <label className="inline-check"><input type="checkbox" checked={includeData} disabled={working} onChange={(e) => setIncludeData(e.target.checked)} /> Include source snapshots</label>
    <p className="caption">{includeData ? "The ZIP will contain the exact selected documents or captured database rows. Treat the download as private." : "The ZIP contains code and source hashes. Supply your files again under the listed aliases; original names, questions and answers are omitted."}</p>
    <label className="inline-check"><input type="checkbox" checked={live} disabled={working || fixture} onChange={(e) => setLive(e.target.checked)} /> Also run a live verification</label>
    <p className="caption">{fixture ? "This saved run uses fixture responses. Live verification is available for live runs." : live ? "This makes a new answer-model call, a query embedding for vector techniques, and up to the saved tree call budget for PageIndex. It reuses the prepared source index. Provider charges may apply; future answers can differ." : "Offline replay uses recorded external responses. It makes no new model calls and does not verify live provider performance."}</p>
    {error && <ErrorNotice message={error} />}
    {item?.error && <ErrorNotice message={item.error.message} />}
    <div className="form-actions"><Button tone="primary" loading={working} disabled={working} onClick={build}>Build export</Button>
      {item?.download_url && <Button loading={busy} disabled={busy} onClick={download}>Download ZIP</Button>}
      {item?.job_id && ["queued", "building"].includes(item.status) && <Button tone="danger" onClick={() => post(`/jobs/${item.job_id}/cancel`, undefined).catch((e) => setError(e.message))}>Cancel build</Button>}
    </div>
    {item && <div role="status"><Status value={item.status} /></div>}
    {item?.manifest && <>
      <h3 className="spaced">Verification</h3>
      {Object.entries(item.manifest.verification).map(([key, result]) => <details key={key} open={key === "offline_replay"}>
        <summary>{key.replaceAll("_", " ")} · {result.status === "not_run" ? "Not performed" : result.status}</summary>
        <p className="caption">{result.details || "This check was not requested."}</p>
        {result.recorded_boundaries.length > 0 && <p className="caption">Recorded boundaries: {result.recorded_boundaries.join(", ")}</p>}
      </details>)}
      <details><summary>Package provenance and limits</summary><dl><dt>Technique</dt><dd>{item.manifest.technique}</dd><dt>Runtime</dt><dd>{item.manifest.runtime_revision}</dd><dt>Sources</dt><dd>{item.manifest.source_hashes.length}</dd></dl>
        {item.manifest.limitations.map((text) => <p className="caption" key={text}>{text}</p>)}
      </details>
    </>}
  </>;
}
