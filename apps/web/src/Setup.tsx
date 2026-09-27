import { useEffect, useState } from "react";
import { api, type Capability } from "./api";
import type { components } from "./generated/api";
import { Button, ErrorNotice } from "./ui";

export function Setup() {
  const [health, setHealth] = useState<components["schemas"]["Health"] | null>(null);
  const [profiles, setProfiles] = useState<components["schemas"]["Profile"][]>([]);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [error, setError] = useState("");
  async function refresh() {
    setError("");
    try {
      const [h, p, c] = await Promise.all([
        api<components["schemas"]["Health"]>("/system/readiness"),
        api<{ items: components["schemas"]["Profile"][] }>("/system/profiles"),
        api<{ items: Capability[] }>("/system/capabilities"),
      ]);
      setHealth(h); setProfiles(p.items); setCapabilities(c.items);
    } catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { void refresh(); }, []);
  return <section className="workspace-content setup-status">
    <div className="section-heading"><h2>Workspace readiness</h2><Button onClick={refresh}>Refresh checks</Button></div>
    {error && <ErrorNotice message={error} />}
    <p role="status">{!health ? "Checking storage…" : health.status === "ok" ? "Database, migrations and artifact storage are ready." : "Storage is unavailable or migrations are pending. Check the services and run the migration command."}</p>
    <p className="caption">Availability checks do not make model calls. Live access is confirmed when a preparation or question succeeds. Queued work requires the worker service.</p>
    <h2 className="spaced">Model profiles</h2>
    {profiles.map((p) => <details key={p.id}><summary>{p.label} · {p.available ? "Configured" : "Unavailable"}</summary><p>{p.unavailable_reason || p.models.join(", ")}</p><p className="caption">Operations: {p.operations.join(", ")}</p></details>)}
    <h2 className="spaced">Retrieval techniques</h2>
    {capabilities.map((c) => <p key={c.technique}><strong>{c.display_name}</strong> · {c.available ? "Available" : c.unavailable_reason}</p>)}
    <p className="caption">Server setup and troubleshooting: docs/17_RUNNING_THE_APPLICATION.md. Model credentials are configured on the server and are never shown here.</p>
  </section>;
}
