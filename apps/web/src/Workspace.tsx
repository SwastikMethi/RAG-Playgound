import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  FileText,
  Plus,
  Settings2,
  Upload,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  post,
  type Bundle,
  type Capability,
  type Configuration,
  type Corpus,
  type Pipeline,
  type Run,
  type Source,
} from "./api";
import { Button, Empty, ErrorNotice, Inspector, Status } from "./ui";
import {
  emptyState,
  reduceEvent,
  replay,
  terminal,
  type Evidence,
  type Playback,
  type TraceEvent,
} from "./reducer";
import { streamEvents } from "./stream";

type View = "playground" | "sources" | "history";
type Inspection =
  | { kind: "source"; source: Source }
  | { kind: "evidence"; evidence: Evidence }
  | { kind: "settings"; config: Configuration };
const ms = (n: number | null | undefined) =>
  n == null
    ? "—"
    : n < 1000
      ? `${Math.round(n)} ms`
      : `${(n / 1000).toFixed(2)} s`;

export function Workspace({
  project,
  capabilities,
  view,
  onView,
}: {
  project: string;
  capabilities: Capability[];
  view: View;
  onView: (view: View) => void;
}) {
  const [sources, setSources] = useState<Source[]>([]),
    [corpora, setCorpora] = useState<Corpus[]>([]),
    [configs, setConfigs] = useState<Configuration[]>([]);
  const [corpusId, setCorpusId] = useState(""),
    [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>(() =>
    JSON.parse(sessionStorage.getItem(`lanes:${project}`) || "[]"),
  );
  const [bundles, setBundles] = useState<Record<string, Bundle>>({});
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [question, setQuestion] = useState("");
  const [run, setRun] = useState<Run | null>(null),
    [history, setHistory] = useState<Run[]>([]),
    [historyQuery, setHistoryQuery] = useState("");
  const [playback, setPlayback] = useState<Playback | null>(null),
    [connected, setConnected] = useState(false),
    [mobileLane, setMobileLane] = useState(0);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]),
    [replaying, setReplaying] = useState(false),
    [cursor, setCursor] = useState(0);
  const savedEvents = useRef<TraceEvent[]>([]);
  const corpus = corpora.find((c) => c.id === corpusId);
  const selectedConfigs = selected
    .map((id) => configs.find((c) => c.id === id))
    .filter((c): c is Configuration => !!c);
  const closeInspector = useCallback(() => setInspection(null), []);
  const load = useCallback(async () => {
    const [s, c, f] = await Promise.all([
      api<{ items: Source[] }>(`/projects/${project}/sources`),
      api<{ items: Corpus[] }>(`/projects/${project}/corpus-versions`),
      api<{ items: Configuration[] }>(`/projects/${project}/configurations`),
    ]);
    setSources(s.items);
    setCorpora(c.items);
    setConfigs(f.items);
    setCorpusId((prior) => prior || c.items[0]?.id || "");
  }, [project]);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);
  useEffect(() => {
    sessionStorage.setItem(`lanes:${project}`, JSON.stringify(selected));
  }, [project, selected]);
  useEffect(() => {
    const map = JSON.parse(
      sessionStorage.getItem(`bundles:${project}:${corpusId}`) || "{}",
    ) as Record<string, string>;
    setBundles({});
    let stale = false;
    Promise.all(
      Object.entries(map).map(
        async ([id, bundle]) =>
          [id, await api<Bundle>(`/index-bundles/${bundle}`)] as const,
      ),
    )
      .then((items) => {
        if (!stale) setBundles(Object.fromEntries(items));
      })
      .catch(() => {});
    return () => {
      stale = true;
    };
  }, [project, corpusId]);
  useEffect(() => {
    const pending = Object.values(bundles).filter((b) =>
      ["queued", "preparing"].includes(b.status),
    );
    if (!sources.some((s) => s.status === "processing") && !pending.length)
      return;
    const timer = setTimeout(() => {
      Promise.all([
        load(),
        ...pending.map(async (b) => {
          const updated = await api<Bundle>(`/index-bundles/${b.id}`);
          setBundles((prior) => ({ ...prior, [b.config_id]: updated }));
        }),
      ]).catch((e) => setError(e.message));
    }, 600);
    return () => clearTimeout(timer);
  }, [sources, bundles, load]);
  useEffect(() => {
    if (view !== "history") return;
    const timer = setTimeout(() => {
      api<{ items: Run[] }>(
        `/projects/${project}/runs?q=${encodeURIComponent(historyQuery)}`,
      )
        .then((r) => setHistory(r.items))
        .catch((e) => setError(e.message));
    }, 200);
    return () => clearTimeout(timer);
  }, [view, project, historyQuery]);
  useEffect(() => {
    if (!run) return;
    const controller = new AbortController();
    let state = emptyState(run.id);
    let attempts = 0;
    savedEvents.current = [];
    setEvents([]);
    setPlayback(state);
    setReplaying(false);
    async function connect() {
      while (!controller.signal.aborted) {
        try {
          setConnected(true);
          await streamEvents(
            run!.id,
            state.lastSeq,
            async (event) => {
              const next = await reduceEvent(state, event);
              if (next.resync)
                throw new Error("Reconnecting to recover an event gap.");
              if (next.lastSeq > state.lastSeq) {
                savedEvents.current.push(event);
                setEvents([...savedEvents.current]);
              }
              state = next;
              setPlayback(next);
              attempts = 0;
            },
            controller.signal,
          );
          if (terminal(state.status)) {
            setConnected(false);
            const latest = await api<Run>(`/runs/${run!.id}`);
            if (!controller.signal.aborted)
              setRun((prior) => (prior?.id === latest.id ? latest : prior));
            return;
          }
        } catch (e) {
          if (controller.signal.aborted) return;
          setConnected(false);
          if (++attempts >= 5) {
            setError((e as Error).message);
            return;
          }
        }
        await new Promise((resolve) =>
          setTimeout(resolve, Math.min(500 * 2 ** attempts, 4000)),
        );
      }
    }
    connect();
    return () => {
      controller.abort();
      setConnected(false);
    };
  }, [run?.id]);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    await action(async () => {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const source = await api<Source>(
          `/projects/${project}/sources/upload`,
          { method: "POST", body: form },
        );
        setSelectedSources((prior) => [...prior, source.id]);
      }
      await load();
    });
  }
  async function freezeCorpus() {
    await action(async () => {
      const c = await post<Corpus>(`/projects/${project}/corpus-versions`, {
        source_ids: selectedSources,
      });
      setCorpusId(c.id);
      await load();
      onView("playground");
    });
  }
  async function addTechnique(capability: Capability) {
    if (!capability.default_config || selected.length >= 6) return;
    await action(async () => {
      const cfg = await post<Configuration>(
        `/projects/${project}/configurations`,
        { name: capability.display_name, config: capability.default_config },
      );
      setConfigs((prior) => [...prior, cfg]);
      setSelected((prior) => [...prior, cfg.id]);
    });
  }
  async function prepare() {
    await action(async () => {
      const next = { ...bundles };
      for (const config of selectedConfigs) {
        if (next[config.id]?.status === "ready") continue;
        next[config.id] = await post<Bundle>(
          `/projects/${project}/preparations`,
          { corpus_version_id: corpusId, config_id: config.id },
          true,
        );
        setBundles({ ...next });
      }
      sessionStorage.setItem(
        `bundles:${project}:${corpusId}`,
        JSON.stringify(
          Object.fromEntries(Object.entries(next).map(([id, b]) => [id, b.id])),
        ),
      );
    });
  }
  async function ask(e: FormEvent) {
    e.preventDefault();
    await action(async () => {
      const result = await post<Run>(
        `/projects/${project}/runs`,
        {
          corpus_version_id: corpusId,
          question,
          lanes: selectedConfigs.map((c) => ({
            config_id: c.id,
            bundle_id: bundles[c.id].id,
          })),
        },
        true,
      );
      setRun(result);
      setMobileLane(0);
      setInspection(null);
    });
  }
  async function seek(seq: number) {
    if (!run) return;
    setReplaying(true);
    setCursor(seq);
    setPlayback(await replay(run.id, events, seq));
  }
  const ready =
    !!corpus &&
    selectedConfigs.length > 0 &&
    selectedConfigs.every((c) => bundles[c.id]?.status === "ready");
  const active = !!run && !terminal(run.status);
  const stageBoundaries = events
    .filter(
      (e) =>
        e.type.startsWith("stage.") ||
        e.type.startsWith("lane.") ||
        e.type.startsWith("run."),
    )
    .map((e) => e.seq);
  return (
    <div className="workspace-body">
      <div className="workspace-content">
        {error && <ErrorNotice message={error} />}
        {view === "sources" ? (
          <>
            <div className="section-heading">
              <div>
                <h2>Source library</h2>
                <p className="muted">
                  Freeze selected sources into a corpus version before
                  comparing.
                </p>
              </div>
              <label className={`button ${busy ? "disabled" : ""}`}>
                <Upload size={16} />
                Upload files
                <input
                  type="file"
                  accept=".pdf,.md,.markdown,.txt"
                  multiple
                  disabled={busy}
                  onChange={(e) => {
                    upload(e.target.files);
                    e.target.value = "";
                  }}
                  className="file-input"
                />
              </label>
            </div>
            {!sources.length ? (
              <Empty title="Give your questions a source">
                <p>Add text-layer PDFs, Markdown or UTF-8 text files.</p>
                <p className="caption">
                  20 MiB per file · 20 sources per corpus · Scanned PDFs need a
                  text layer.
                </p>
              </Empty>
            ) : (
              <div className="panel source-list">
                {sources.map((source) => (
                  <div key={source.id} className="source-row">
                    <input
                      type="checkbox"
                      aria-label={`Include ${source.display_name}`}
                      disabled={source.status !== "ready"}
                      checked={selectedSources.includes(source.id)}
                      onChange={(e) =>
                        setSelectedSources((prior) =>
                          e.target.checked
                            ? [...prior, source.id]
                            : prior.filter((id) => id !== source.id),
                        )
                      }
                    />
                    <FileText size={22} />
                    <button
                      className="source-name"
                      onClick={() => setInspection({ kind: "source", source })}
                    >
                      <strong>{source.display_name}</strong>
                      <span className="caption">
                        {source.metadata.format as string} ·{" "}
                        {Math.round((source.size_bytes || 0) / 1024)} KB
                      </span>
                      {source.error && (
                        <span className="error-text">
                          {source.error.message}
                        </span>
                      )}
                    </button>
                    <Status value={source.status} />
                  </div>
                ))}
                <div className="source-footer">
                  <span className="muted">
                    {selectedSources.length} selected
                  </span>
                  <Button
                    tone="primary"
                    disabled={
                      busy ||
                      !selectedSources.length ||
                      selectedSources.some(
                        (id) =>
                          sources.find((s) => s.id === id)?.status !== "ready",
                      )
                    }
                    onClick={freezeCorpus}
                  >
                    Use selected sources
                    <ChevronRight size={16} />
                  </Button>
                </div>
              </div>
            )}
          </>
        ) : view === "history" ? (
          <>
            <div className="section-heading">
              <div>
                <h2>Comparison history</h2>
                <p className="muted">
                  Saved answers, evidence and recorded execution.
                </p>
              </div>
              <input
                aria-label="Search question history"
                placeholder="Search questions…"
                value={historyQuery}
                onChange={(e) => setHistoryQuery(e.target.value)}
              />
            </div>
            {!history.length ? (
              <Empty title="No saved comparisons">
                <p>Run a question in the playground to start a history.</p>
              </Empty>
            ) : (
              <div className="history-list">
                {history.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => {
                      setRun(item);
                      onView("playground");
                    }}
                  >
                    <div>
                      <strong>{item.question}</strong>
                      <span className="caption">
                        {new Date(item.created_at).toLocaleString()} ·{" "}
                        {item.lanes.length} lanes
                      </span>
                    </div>
                    <Status value={item.status} />
                    <ChevronRight size={18} />
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <section className="setup-bar">
              <div>
                <label className="caption">
                  CORPUS
                  <select
                    value={corpusId}
                    onChange={(e) => setCorpusId(e.target.value)}
                    disabled={active}
                  >
                    {!corpusId && (
                      <option value="">Choose source documents</option>
                    )}
                    {corpora.map((c) => (
                      <option key={c.id} value={c.id}>
                        Version {c.ordinal} · {c.source_ids.length} sources
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <Button onClick={() => onView("sources")}>
                <BookOpen size={16} />
                {corpus ? "Manage sources" : "Add sources"}
              </Button>
              <div className="setup-spacer" />
              <span className="caption">{selectedConfigs.length}/6 lanes</span>
              <Button
                disabled={
                  busy || !corpus || !selectedConfigs.length || ready || active
                }
                onClick={prepare}
              >
                {ready ? (
                  <>
                    <Check size={16} />
                    Ready to compare
                  </>
                ) : (
                  "Prepare selected"
                )}
              </Button>
            </section>
            <details
              className="technique-picker"
              open={!selectedConfigs.length}
            >
              <summary>
                Choose retrieval techniques{" "}
                <span className="caption">
                  Different routes to the same evidence
                </span>
              </summary>
              <div className="technique-grid">
                {capabilities.map((c) => (
                  <button
                    key={c.technique}
                    className="technique-option"
                    disabled={
                      !c.available || busy || selected.length >= 6 || active
                    }
                    onClick={() => addTechnique(c)}
                  >
                    <div>
                      <h3>{c.display_name}</h3>
                      <Plus size={16} />
                    </div>
                    <p>{c.description}</p>
                    {!c.available && (
                      <span className="caption">{c.unavailable_reason}</span>
                    )}
                  </button>
                ))}
              </div>
            </details>
            {!!selectedConfigs.length && (
              <div className="selected-lanes">
                {selectedConfigs.map((config) => (
                  <div key={config.id} className="lane-chip">
                    <button
                      onClick={() =>
                        setInspection({ kind: "settings", config })
                      }
                    >
                      {config.name}
                      <span className="caption"> v{config.revision}</span>
                    </button>
                    <Status
                      value={bundles[config.id]?.status || "needs preparation"}
                    />
                    <Button
                      aria-label={`Remove ${config.name}`}
                      disabled={active}
                      onClick={() =>
                        setSelected((prior) =>
                          prior.filter((id) => id !== config.id),
                        )
                      }
                    >
                      <X size={14} />
                    </Button>
                    {bundles[config.id]?.error && (
                      <span className="error-text">
                        {bundles[config.id].error?.message}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
            <form className="question-box" onSubmit={ask}>
              <label className="sr-only" htmlFor="question">
                Question for all selected lanes
              </label>
              <textarea
                id="question"
                placeholder="What would you like to understand?"
                rows={2}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={8000}
              />
              <div>
                <span className="caption">
                  {ready
                    ? `Same question · ${selectedConfigs[0]?.config.generation.model} · ${selectedConfigs[0]?.config.generation.context_budget_tokens.toLocaleString()} context tokens`
                    : "Add sources and prepare at least one technique to ask."}
                </span>
                <Button
                  tone="primary"
                  type="submit"
                  disabled={!ready || busy || active || !question.trim()}
                >
                  <ArrowUp size={17} />
                  Ask all lanes
                </Button>
              </div>
            </form>
            {!run ? (
              <Empty title="A question. Several perspectives.">
                <p>
                  Your answers will appear side by side, with sources and
                  measured steps for each technique.
                </p>
              </Empty>
            ) : (
              <>
                <div className="comparison-heading">
                  <div>
                    <h2>{run.question}</h2>
                    <span className="caption">
                      {replaying
                        ? "Replay of saved execution"
                        : connected
                          ? "Receiving saved events"
                          : terminal(playback?.status || "")
                            ? "Saved comparison"
                            : "Reconnecting…"}{" "}
                      · Queue {ms(run.queue_ms)} · Timings describe this run
                    </span>
                  </div>
                  <Status value={playback?.status || run.status} />
                </div>
                {terminal(run.status) && events.length > 0 && (
                  <div className="replay-bar">
                    <Button
                      onClick={() =>
                        seek(
                          stageBoundaries
                            .filter(
                              (s) => s < (replaying ? cursor : events.length),
                            )
                            .at(-1) || 0,
                        )
                      }
                    >
                      Previous step
                    </Button>
                    <Button
                      onClick={() =>
                        seek(
                          stageBoundaries.find(
                            (s) => s > (replaying ? cursor : 0),
                          ) || events.length,
                        )
                      }
                    >
                      Next step
                    </Button>
                    <input
                      aria-label="Replay position"
                      type="range"
                      min={0}
                      max={events.length}
                      value={replaying ? cursor : events.length}
                      onChange={(e) => seek(Number(e.target.value))}
                    />
                    <Button
                      onClick={async () => {
                        setPlayback(await replay(run.id, events));
                        setReplaying(false);
                      }}
                    >
                      Show final answer
                    </Button>
                  </div>
                )}
                <label className="mobile-lane-select">
                  Compare lane
                  <select
                    value={mobileLane}
                    onChange={(e) => setMobileLane(Number(e.target.value))}
                  >
                    {run.lanes.map((lane, i) => (
                      <option key={lane.id} value={i}>
                        {configs.find((c) => c.id === lane.config_id)?.name ||
                          lane.technique}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="answer-grid">
                  {run.lanes.map((lane, i) => {
                    const state = playback?.lanes[lane.id];
                    const config = configs.find((c) => c.id === lane.config_id);
                    return (
                      <article
                        key={lane.id}
                        className={`answer-lane ${mobileLane === i ? "mobile-active" : ""}`}
                      >
                        <header>
                          <div>
                            <h3>
                              {config?.name ||
                                capabilities.find(
                                  (c) => c.technique === lane.technique,
                                )?.display_name}
                            </h3>
                            <span className="caption">
                              Revision {config?.revision || 1}
                            </span>
                          </div>
                          <Status value={state?.status || "queued"} />
                        </header>
                        <div className="lane-tools">
                          <span>
                            Total{" "}
                            <strong>{ms(state?.metrics?.total_ms)}</strong>
                          </span>
                          <span>
                            First token{" "}
                            <strong>{ms(state?.metrics?.ttft_ms)}</strong>
                          </span>
                          {config && (
                            <Button
                              aria-label={`Settings for ${config.name}`}
                              onClick={() =>
                                setInspection({ kind: "settings", config })
                              }
                            >
                              <Settings2 size={15} />
                            </Button>
                          )}
                        </div>
                        <div className="answer-text">
                          {state?.answer ? (
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                img: () => null,
                                a: ({ href, children }) =>
                                  href?.startsWith("#evidence-") ? (
                                    <button
                                      className="citation"
                                      onClick={() => {
                                        const e = state.evidence.find(
                                          (e) => e.label === href.slice(10),
                                        );
                                        if (e)
                                          setInspection({
                                            kind: "evidence",
                                            evidence: e,
                                          });
                                      }}
                                    >
                                      {children}
                                    </button>
                                  ) : (
                                    <span>{children}</span>
                                  ),
                              }}
                            >
                              {state.answer.replace(
                                /\[(E[1-9][0-9]*)\]/g,
                                "[$1](#evidence-$1)",
                              )}
                            </ReactMarkdown>
                          ) : (
                            <p className="muted">
                              {state?.status === "running"
                                ? "Retrieving evidence…"
                                : "Waiting for this lane."}
                            </p>
                          )}
                          {state?.error && (
                            <ErrorNotice message={state.error} />
                          )}
                        </div>
                        <div className="lane-evidence">
                          {state?.evidence.map((e) => (
                            <button
                              key={e.evidence_id}
                              onClick={() =>
                                setInspection({ kind: "evidence", evidence: e })
                              }
                            >
                              <span>{e.label}</span>
                              {e.source_name}
                              <ChevronRight size={14} />
                            </button>
                          ))}
                        </div>
                        <details className="lane-details">
                          <summary>
                            Execution steps ·{" "}
                            {Object.keys(state?.stages || {}).length}
                          </summary>
                          <ol>
                            {Object.values(state?.stages || {}).map((step) => (
                              <li key={step.id}>
                                <span>{step.name.replaceAll("_", " ")}</span>
                                <Status value={step.status} />
                                <span className="caption">
                                  {ms(step.duration)}
                                </span>
                                {step.error && (
                                  <p className="error-text">{step.error}</p>
                                )}
                              </li>
                            ))}
                          </ol>
                        </details>
                        {!!state?.warnings.length && (
                          <details className="lane-details">
                            <summary>
                              {state.warnings.length} notice
                              {state.warnings.length > 1 ? "s" : ""}
                            </summary>
                            {state.warnings.map((w, i) => (
                              <p key={i} className="caption">
                                {w}
                              </p>
                            ))}
                          </details>
                        )}
                        <span className="sr-only" role="status">
                          {terminal(state?.status || "")
                            ? `Lane ${i + 1} ${state?.status}`
                            : ""}
                        </span>
                      </article>
                    );
                  })}
                </div>
              </>
            )}
          </>
        )}
      </div>
      {inspection && (
        <Inspector
          title={
            inspection.kind === "settings"
              ? "Pipeline settings"
              : inspection.kind === "evidence"
                ? "Source evidence"
                : "Source preview"
          }
          onClose={closeInspector}
        >
          {inspection.kind === "settings" ? (
            <ConfigurationForm
              config={inspection.config}
              busy={busy}
              save={(config) =>
                action(async () => {
                  const saved = await post<Configuration>(
                    `/projects/${project}/configurations`,
                    {
                      name: inspection.config.name,
                      config,
                      based_on_config_id: inspection.config.id,
                    },
                  );
                  setConfigs((prior) => [...prior, saved]);
                  setSelected((prior) =>
                    prior.map((id) =>
                      id === inspection.config.id ? saved.id : id,
                    ),
                  );
                  setInspection({ kind: "settings", config: saved });
                })
              }
            />
          ) : (
            <SourceInspector inspection={inspection} />
          )}
        </Inspector>
      )}
    </div>
  );
}

function SourceInspector({
  inspection,
}: {
  inspection: Exclude<Inspection, { kind: "settings" }>;
}) {
  const [preview, setPreview] = useState(""),
    [error, setError] = useState("");
  const evidence = inspection.kind === "evidence" ? inspection.evidence : null;
  const sourceId =
    evidence?.source_id ||
    (inspection.kind === "source" ? inspection.source.id : "");
  useEffect(() => {
    setPreview("");
    setError("");
    const query = evidence
      ? `?start_char=${evidence.location.char_start || 0}&max_chars=12000`
      : "";
    api<{ content: string }>(`/sources/${sourceId}/content${query}`)
      .then((p) => setPreview(p.content))
      .catch((e) => setError(e.message));
  }, [sourceId, evidence]);
  return (
    <>
      <h3>
        {evidence?.source_name ||
          (inspection.kind === "source" ? inspection.source.display_name : "")}
      </h3>
      {evidence && (
        <>
          <div className="evidence-label">
            {evidence.label} ·{" "}
            {evidence.location.page_start
              ? `Page ${evidence.location.page_start}`
              : `Lines ${evidence.location.line_start}–${evidence.location.line_end}`}
          </div>
          <p className="caption">
            This exact passage was supplied to the answer model.
            {evidence.span_truncated
              ? " Trimmed to fit the context budget."
              : ""}
          </p>
          <blockquote className="evidence-excerpt">
            {evidence.excerpt}
          </blockquote>
          <details>
            <summary>Retrieval details</summary>
            <dl>
              <dt>Rank</dt>
              <dd>{evidence.rank}</dd>
              <dt>Score type</dt>
              <dd>{evidence.score_type}</dd>
              <dt>Score</dt>
              <dd>{evidence.score?.toFixed(4) || "—"}</dd>
              <dt>Code-point span</dt>
              <dd>
                {evidence.location.char_start}–{evidence.location.char_end}
              </dd>
            </dl>
            <p className="caption">
              Scores are specific to this retrieval method and are not
              answer-quality ratings.
            </p>
          </details>
        </>
      )}
      <h3 className="spaced">Source text</h3>
      {error ? (
        <ErrorNotice message={error} />
      ) : (
        <pre className="source-preview">
          {preview || "Loading source text…"}
        </pre>
      )}
      <p className="caption">
        Citation labels can be checked syntactically. You decide whether the
        source supports the answer.
      </p>
    </>
  );
}

function ConfigurationForm({
  config,
  busy,
  save,
}: {
  config: Configuration;
  busy: boolean;
  save: (config: Pipeline) => void;
}) {
  const [draft, setDraft] = useState<Pipeline>(structuredClone(config.config));
  useEffect(() => setDraft(structuredClone(config.config)), [config.id]);
  const number = (
    section: "search" | "generation",
    field: string,
    label: string,
    min: number,
    max: number,
  ) => (
    <label>
      {label}
      <input
        type="number"
        min={min}
        max={max}
        value={Number((draft[section] as Record<string, unknown>)[field])}
        onChange={(e) =>
          setDraft((prior) => ({
            ...prior,
            [section]: { ...prior[section], [field]: Number(e.target.value) },
          }))
        }
      />
    </label>
  );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save(draft);
      }}
    >
      <h3>{config.name}</h3>
      <p className="caption">
        Saving creates a new revision. Prepare it before running. Generation
        settings must match across compared lanes.
      </p>
      {number("search", "candidate_k", "Candidate passages", 1, 100)}
      {number("search", "context_k", "Context passages", 1, 20)}
      {number(
        "generation",
        "context_budget_tokens",
        "Context token budget",
        256,
        16000,
      )}
      {number(
        "generation",
        "max_output_tokens",
        "Maximum answer tokens",
        64,
        4096,
      )}
      <label>
        Temperature
        <input
          type="number"
          min={0}
          max={2}
          step={0.1}
          value={draft.generation.temperature}
          onChange={(e) =>
            setDraft({
              ...draft,
              generation: {
                ...draft.generation,
                temperature: Number(e.target.value),
              },
            })
          }
        />
      </label>
      {draft.chunking && (
        <>
          <label>
            Chunk strategy
            <select
              value={draft.chunking.strategy}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  chunking: {
                    ...draft.chunking!,
                    strategy: e.target.value as "headings" | "fixed_tokens",
                  },
                })
              }
            >
              <option value="fixed_tokens">Fixed token windows</option>
              <option value="headings">Respect headings</option>
            </select>
          </label>
          <label>
            Chunk size (tokens)
            <input
              type="number"
              min={64}
              max={2048}
              value={draft.chunking.size_tokens}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  chunking: {
                    ...draft.chunking!,
                    size_tokens: Number(e.target.value),
                  },
                })
              }
            />
          </label>
          <label>
            Overlap (tokens)
            <input
              type="number"
              min={0}
              max={512}
              value={draft.chunking.overlap_tokens}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  chunking: {
                    ...draft.chunking!,
                    overlap_tokens: Number(e.target.value),
                  },
                })
              }
            />
          </label>
        </>
      )}
      <details>
        <summary>Full effective configuration</summary>
        <pre className="source-preview">
          {JSON.stringify(config.config, null, 2)}
        </pre>
      </details>
      <Button type="submit" tone="primary" disabled={busy}>
        Save new revision
      </Button>
    </form>
  );
}
