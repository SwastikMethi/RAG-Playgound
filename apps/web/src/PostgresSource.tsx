import { useEffect, useState, type FormEvent } from "react";
import { api, post, type Source } from "./api";
import type { components } from "./generated/api";
import { Button, ErrorNotice } from "./ui";

type Connection = components["schemas"]["PublicConnection"];
type Relation = components["schemas"]["Relation"];
type Selection = components["schemas"]["CapturePostgres"];
type Preview = components["schemas"]["PostgresPreview"];

export function PostgresSource({
  project,
  initial,
  onCaptured,
  onReady,
}: {
  project: string;
  initial?: Source;
  onCaptured: (s: Source) => void;
  onReady: (s: Source) => Promise<void>;
}) {
  const saved = initial?.metadata.selection as Selection | undefined;
  const [connections, setConnections] = useState<Connection[]>([]),
    [connection, setConnection] = useState(saved?.connection_id || "");
  const [relations, setRelations] = useState<Relation[]>([]),
    [relationIndex, setRelationIndex] = useState(-1);
  const [keys, setKeys] = useState<string[]>(saved?.key_columns || []),
    [texts, setTexts] = useState<string[]>(saved?.text_columns || []);
  const [updated, setUpdated] = useState(saved?.updated_at_column || ""),
    [maxRows, setMaxRows] = useState(saved?.max_rows || 10000);
  const [name, setName] = useState(
    initial ? `${initial.display_name} · refreshed` : "Database snapshot",
  );
  const [preview, setPreview] = useState<Preview | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [jobId, setJobId] = useState("");
  const [add, setAdd] = useState(false);
  async function load() {
    const result = await api<{ items: Connection[] }>(
      `/projects/${project}/connections`,
    );
    setConnections(result.items);
    if (!result.items.length) setAdd(true);
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [project]);
  useEffect(() => {
    setRelations([]);
    setRelationIndex(-1);
    setPreview(null);
    if (!connection) return;
    let ignore = false;
    api<{ items: Relation[] }>(`/connections/${connection}/relations`)
      .then((r) => {
        if (ignore) return;
        setRelations(r.items);
        const index = saved
          ? r.items.findIndex(
              (x) => x.schema === saved.schema && x.name === saved.relation,
            )
          : -1;
        if (index >= 0) setRelationIndex(index);
      })
      .catch((e) => {
        if (!ignore) setError(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [connection]);
  const relation = relations[relationIndex];
  const selection: Selection = {
    connection_id: connection,
    schema: relation?.schema || "",
    relation: relation?.name || "",
    key_columns: keys,
    text_columns: texts,
    updated_at_column: updated || null,
    max_rows: maxRows,
    display_name: name,
  };
  const ready =
    !!relation && keys.length > 0 && texts.length > 0 && !!name.trim();
  async function work(fn: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function saveConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget,
      data = new FormData(form);
    await work(async () => {
      const result = await post<Connection>(
        `/projects/${project}/connections`,
        {
          name: data.get("name"),
          host: data.get("host"),
          port: Number(data.get("port")),
          database: data.get("database"),
          username: data.get("username"),
          password: data.get("password"),
          ssl_mode: data.get("ssl_mode"),
          allowed_schemas: String(data.get("schemas"))
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        },
      );
      form.reset();
      await load();
      setConnection(result.id);
      setAdd(false);
    });
  }
  const toggle = (values: string[], key: string, checked: boolean) =>
    checked ? [...values, key] : values.filter((v) => v !== key);
  return (
    <>
      <p className="muted">
        Capture selected text once, then ask questions against that saved
        snapshot. Queries do not reconnect to your database.
      </p>
      {error && <ErrorNotice message={error} />}
      <label className="spaced">
        Connection
        <select
          aria-label="Database connection"
          value={connection}
          disabled={busy}
          onChange={(e) => {
            setConnection(e.target.value);
            setError("");
          }}
        >
          <option value="">Choose a connection</option>
          {connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} · {c.database}
            </option>
          ))}
        </select>
      </label>
      <div className="button-row">
        <Button disabled={busy} onClick={() => setAdd(!add)}>
          {add ? "Close connection form" : "New connection"}
        </Button>
        {connection && (
          <Button
            disabled={busy}
            onClick={() => {
              if (
                confirm(
                  "Remove these saved credentials? Existing snapshots remain available.",
                )
              )
                void work(async () => {
                  await api(`/connections/${connection}`, { method: "DELETE" });
                  setConnection("");
                  await load();
                });
            }}
          >
            Remove connection
          </Button>
        )}
      </div>
      {add && (
        <form className="connection-form spaced" onSubmit={saveConnection}>
          <h3>Read-only connection</h3>
          <p className="caption">
            The server owner must configure the encryption key and approve this
            host, relation and columns. Use a dedicated read-only database role.
          </p>
          {[
            ["name", "Connection name", "text", ""],
            ["host", "Host", "text", ""],
            ["port", "Port", "number", "5432"],
            ["database", "Database", "text", ""],
            ["username", "Username", "text", ""],
            ["password", "Password", "password", ""],
            ["schemas", "Allowed schemas (comma separated)", "text", "public"],
          ].map(([field, label, type, initial]) => (
            <label key={field}>
              {label}
              <input
                name={field}
                type={type}
                required
                defaultValue={initial}
                min={field === "port" ? 1 : undefined}
                max={field === "port" ? 65535 : undefined}
                maxLength={field === "password" ? 4096 : 300}
                autoComplete={field === "password" ? "new-password" : "off"}
              />
            </label>
          ))}
          <label>
            TLS
            <select name="ssl_mode" defaultValue="verify-full">
              <option value="verify-full">Verify server identity</option>
              <option value="require">Require encrypted connection</option>
              <option value="disable">
                Disable (trusted local development only)
              </option>
            </select>
          </label>
          <Button type="submit" tone="primary" disabled={busy}>
            Save and inspect
          </Button>
        </form>
      )}
      {connection && (
        <>
          <label className="spaced">
            Approved relation
            <select
              aria-label="Approved relation"
              value={relationIndex}
              disabled={busy}
              onChange={(e) => {
                const i = Number(e.target.value);
                setRelationIndex(i);
                setPreview(null);
                setUpdated("");
                const r = relations[i];
                setKeys(r?.suggested_key_columns || []);
                setTexts(
                  r?.columns
                    .filter(
                      (c) =>
                        /text|char/.test(c.data_type) &&
                        !r.suggested_key_columns.includes(c.name),
                    )
                    .map((c) => c.name) || [],
                );
              }}
            >
              <option value={-1}>
                {relations.length
                  ? "Choose a table or view"
                  : "No approved relations loaded"}
              </option>
              {relations.map((r, i) => (
                <option key={i} value={i}>
                  {r.schema}.{r.name} · {r.kind}
                </option>
              ))}
            </select>
          </label>
          {relation && (
            <>
              <h3 className="spaced">Select captured columns</h3>
              <p className="caption">
                Keys must uniquely identify every row and contain no nulls. Only
                checked text columns are copied.
              </p>
              <table className="column-table">
                <thead>
                  <tr>
                    <th>Column</th>
                    <th>Key</th>
                    <th>Text</th>
                  </tr>
                </thead>
                <tbody>
                  {relation.columns.map((c) => (
                    <tr key={c.name}>
                      <td>
                        {c.name}
                        <span className="caption">
                          {c.data_type}
                          {c.nullable ? " · nullable" : ""}
                        </span>
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Key column ${c.name}`}
                          checked={keys.includes(c.name)}
                          disabled={
                            busy || (!keys.includes(c.name) && keys.length >= 8)
                          }
                          onChange={(e) => {
                            setKeys(toggle(keys, c.name, e.target.checked));
                            setPreview(null);
                          }}
                        />
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Text column ${c.name}`}
                          checked={texts.includes(c.name)}
                          disabled={
                            busy ||
                            (!texts.includes(c.name) && texts.length >= 20)
                          }
                          onChange={(e) => {
                            setTexts(toggle(texts, c.name, e.target.checked));
                            setPreview(null);
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <label className="spaced">
                Updated timestamp (optional)
                <select
                  value={updated}
                  onChange={(e) => setUpdated(e.target.value)}
                  disabled={busy}
                >
                  <option value="">None</option>
                  {relation.columns.map((c) => (
                    <option key={c.name}>{c.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Maximum rows
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={maxRows}
                  onChange={(e) => {
                    setMaxRows(Number(e.target.value));
                    setPreview(null);
                  }}
                  disabled={busy}
                />
              </label>
              <label>
                Snapshot name
                <input
                  maxLength={300}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={busy}
                />
              </label>
              <p className="caption">
                Up to 10,000 rows and 20 MiB, ordered by the chosen key. Empty
                records are skipped. This is a text snapshot; it cannot
                calculate aggregates over uncaptured rows.
              </p>
              <div className="button-row">
                <Button
                  disabled={!ready || busy}
                  onClick={() =>
                    work(async () =>
                      setPreview(
                        await post<Preview>(
                          `/connections/${connection}/preview`,
                          selection,
                        ),
                      ),
                    )
                  }
                >
                  Preview five records
                </Button>
                <Button
                  tone="primary"
                  disabled={!ready || busy}
                  onClick={() =>
                    work(async () => {
                      let source = await post<Source>(
                        `/projects/${project}/sources/postgres`,
                        selection,
                      );
                      onCaptured(source);
                      setJobId(source.job_id || "");
                      while (source.status === "processing") {
                        await new Promise((r) => setTimeout(r, 750));
                        source = await api<Source>(`/sources/${source.id}`);
                      }
                      setJobId("");
                      if (source.status !== "ready")
                        throw new Error(
                          source.error?.message || "Snapshot capture stopped.",
                        );
                      await onReady(source);
                    })
                  }
                >
                  {jobId
                    ? "Capturing…"
                    : initial
                      ? "Capture new revision"
                      : "Capture snapshot"}
                </Button>
                {jobId && (
                  <Button
                    onClick={() =>
                      post(`/jobs/${jobId}/cancel`, {}).catch((e) =>
                        setError(e.message),
                      )
                    }
                  >
                    Cancel capture
                  </Button>
                )}
              </div>
              {preview && (
                <section className="snapshot-preview spaced">
                  <h3>Preview · {preview.rows.length} records</h3>
                  <p className="caption">
                    {preview.ordering}
                    {preview.truncated ? " · More rows or text exist" : ""}
                  </p>
                  {preview.rows.map((r, i) => (
                    <article key={i}>
                      <strong>{JSON.stringify(r.key)}</strong>
                      <pre>{r.text}</pre>
                    </article>
                  ))}
                </section>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
