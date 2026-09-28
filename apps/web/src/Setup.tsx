import { useEffect, useState } from "react";
import { api, type Capability } from "./api";
import type { components } from "./generated/api";
import type { ModelOptions, ModelSelection } from "./modelDefaults";
import { Button, ErrorNotice, Loading } from "./ui";

import { AccountSettings } from "./Accounts";

export function Setup({
  hosted = false,
  modelSelection,
  modelOptions,
  modelStatus,
  modelError,
  onModelSelection,
  onRefreshModels,
  onKeyChanged = () => {},
}: {
  hosted?: boolean;
  modelSelection: ModelSelection;
  modelOptions: ModelOptions;
  modelStatus: "loading" | "ready" | "error";
  modelError: string;
  onModelSelection: (selection: ModelSelection) => void;
  onRefreshModels: () => Promise<void>;
  onKeyChanged?: () => void;
}) {
  const [health, setHealth] = useState<components["schemas"]["Health"] | null>(null);
  const [profiles, setProfiles] = useState<components["schemas"]["Profile"][]>([]);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  async function refresh() {
    setError(""); setChecking(true);
    try {
      const [h, p, c] = await Promise.all([
        api<components["schemas"]["Health"]>("/system/readiness"),
        api<{ items: components["schemas"]["Profile"][] }>("/system/profiles"),
        api<{ items: Capability[] }>("/system/capabilities"),
      ]);
      setHealth(h); setProfiles(p.items); setCapabilities(c.items);
    } catch (e) { setError((e as Error).message); }
    finally { setChecking(false); }
  }
  useEffect(() => { void refresh(); }, []);
  return <section className="workspace-content setup-status">
    {hosted && <AccountSettings onKeyChanged={() => { void onRefreshModels(); void refresh(); onKeyChanged(); }} />}
    <div className="section-heading"><h2>Workspace readiness</h2><Button loading={checking || modelStatus === "loading"} onClick={() => { void refresh(); void onRefreshModels(); }}>Refresh checks</Button></div>
    {error && <ErrorNotice message={error} />}
    <p role="status">{!health ? <><Loading label="Checking workspace storage" /> Checking storage…</> : health.status === "ok" ? "Database, migrations and artifact storage are ready." : "Storage is unavailable or migrations are pending. Check the services and run the migration command."}</p>
    <p className="caption">Availability checks do not make model calls. Live access is confirmed when a preparation or question succeeds. Queued work requires the worker service.</p>
    <h2 className="spaced">Pipeline models</h2>
    <p className="caption">These models apply to new pipelines immediately and to every selected pipeline when you Prepare. Existing runs and saved revisions stay immutable.</p>
    {modelStatus === "loading" && <p role="status"><Loading label="Checking compatible models" /> Checking compatible models…</p>}
    {modelError && <ErrorNotice message={modelError} />}
    <div className="model-selectors">
      <label>Answer model<select aria-label="Answer model" value={modelSelection.generation?.id || ""} disabled={modelStatus !== "ready"} onChange={(event) => onModelSelection({ ...modelSelection, generation: modelOptions.generation.find((profile) => profile.id === event.target.value) })}>
        {!modelOptions.generation.length && <option value="">Save a compatible OpenAI key</option>}
        {modelOptions.generation.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
      </select></label>
      <label>Embedding model<select aria-label="Embedding model" value={modelSelection.embedding?.id || ""} disabled={modelStatus !== "ready"} onChange={(event) => onModelSelection({ ...modelSelection, embedding: modelOptions.embedding.find((profile) => profile.id === event.target.value) })}>
        {!modelOptions.embedding.length && <option value="">Save a compatible OpenAI key</option>}
        {modelOptions.embedding.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
      </select></label>
    </div>
    <h2 className="spaced">Model profiles</h2>
    {profiles.map((p) => <details key={p.id}><summary>{p.label} · {p.available ? "Configured" : "Unavailable"}</summary><p>{p.unavailable_reason || p.models.join(", ")}</p><p className="caption">Operations: {p.operations.join(", ")}</p></details>)}
    <h2 className="spaced">Retrieval techniques</h2>
    {capabilities.map((c) => <p key={c.technique}><strong>{c.display_name}</strong> · {c.available ? "Available" : c.unavailable_reason}</p>)}
    {!hosted && <p className="caption">Server setup and troubleshooting: docs/17_RUNNING_THE_APPLICATION.md. Model credentials are configured on the server and are never shown here.</p>}
  </section>;
}
