import type { components } from "./generated/api";
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
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  apiAll,
  post,
  downloadFile,
  type Bundle,
  type Capability,
  type Configuration,
  type Corpus,
  type Pipeline,
  type Lane,
  type Run,
  type Source,
} from "./api";
import { Button, Empty, ErrorNotice, Inspector, Loading, Status } from "./ui";
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
import { DeleteSource } from "./DeleteSource";
import { LaneFeedback, RunPreference } from "./Judgement";
import { ExportPanel } from "./ExportPanel";
import { PostgresSource } from "./PostgresSource";
import { Workflow, StepInspector, LiveDuration } from "./Workflow";
import {
  applyModelDefaults,
  pipelineUsesModels,
  type ModelSelection,
} from "./modelDefaults";
import {
  MAX_CORPUS_BYTES,
  MAX_CORPUS_SOURCES,
  formatBytes,
  selectedSourceBytes,
  sourceSelectionError as selectionError,
} from "./sourceSelection";

type View = "playground" | "sources" | "history";
type Inspection =
  | { kind: "delete"; source: Source }
  | { kind: "export"; lane: Lane; runId: string }
  | { kind: "postgres"; source?: Source }
  | { kind: "source"; source: Source }
  | { kind: "evidence"; evidence: Evidence }
  | { kind: "step"; laneId: string; spanId: string }
  | { kind: "settings"; config: Configuration };
const ms = (n: number | null | undefined) =>
  n == null
    ? "—"
    : n < 1000
      ? `${Math.round(n)} ms`
      : `${(n / 1000).toFixed(2)} s`;

// Stable component identities preserve citation focus as new events render.
const answerComponents: Components = {
  img: () => null,
  a: ({ href, children }) => href?.startsWith("#evidence-")
    ? <button className="citation" data-citation={href.slice(10)}>{children}</button>
    : <span>{children}</span>,
};

export function Workspace({
  project,
  capabilities,
  modelSelection,
  modelsReady,
  view,
  onView,
}: {
  project: string;
  capabilities: Capability[];
  modelSelection: ModelSelection;
  modelsReady: boolean;
  view: View;
  onView: (view: View) => void;
}) {
  const [sources, setSources] = useState<Source[]>([]),
    [corpora, setCorpora] = useState<Corpus[]>([]),
    [configs, setConfigs] = useState<Configuration[]>([]);
  const [corpusId, setCorpusId] = useState(""),
    [selectedSources, setSelectedSources] = useState<string[]>([]);
  const selectedBytes = selectedSourceBytes(sources, selectedSources);
  const sourceSelectionError = selectionError(selectedSources.length, selectedBytes);
  const [selected, setSelected] = useState<string[]>(() =>
    JSON.parse(sessionStorage.getItem(`lanes:${project}`) || "[]"),
  );
  const [bundles, setBundles] = useState<Record<string, Bundle>>({});
  const [error, setError] = useState(""),
    [busyTask, setBusyTask] = useState(""),
    [question, setQuestion] = useState("");
  const busy = Boolean(busyTask);
  const [run, setRun] = useState<Run | null>(null),
    [history, setHistory] = useState<Run[]>([]),
    [historyQuery, setHistoryQuery] = useState("");
  const [historyStatus, setHistoryStatus] = useState("");
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [setupOpen, setSetupOpen] = useState(true);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [disconnected, setDisconnected] = useState(false);
  const [playback, setPlayback] = useState<Playback | null>(null),
    [connected, setConnected] = useState(false),
    [mobileLane, setMobileLane] = useState(0);
  const [inspection, updateInspection] = useState<Inspection | null>(null);
  const [followLane, setFollowLane] = useState<string | null>(null);
  const setInspection = useCallback((value: Inspection | null) => {
    setFollowLane(null);
    updateInspection(value);
  }, []);
  const [tabs, setTabs] = useState<Record<string, string>>({});
  const [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(1),
    [compressed, setCompressed] = useState(false);
  const seekRequest = useRef(0);
  const [events, setEvents] = useState<TraceEvent[]>([]),
    [replaying, setReplaying] = useState(false),
    [cursor, setCursor] = useState(0);
  const savedEvents = useRef<TraceEvent[]>([]);
  useEffect(() => {
    if (!followLane || !playback) return;
    const last = Object.values(playback.lanes[followLane]?.stages || {}).at(-1);
    if (last)
      updateInspection({ kind: "step", laneId: followLane, spanId: last.id });
  }, [followLane, playback]);
  useEffect(() => {
    setPlaying(false);
    setFollowLane(null);
    setTabs({});
    setSpeed(Number(sessionStorage.getItem(`replay-speed:${run?.id}`) || 1));
  }, [run?.id]);
  useEffect(() => {
    if (!playing || !run) return;
    if (cursor >= events.length) {
      setPlaying(false);
      return;
    }
    const gap =
      events[cursor].elapsed_ms - (events[cursor - 1]?.elapsed_ms || 0);
    const delay = (compressed ? Math.min(gap, 1000) : gap) / speed;
    const timer = setTimeout(
      () => {
        void seek(cursor + 1);
      },
      Math.max(0, delay),
    );
    return () => clearTimeout(timer);
  }, [playing, cursor, events, speed, compressed, run?.id]);
  const corpus = corpora.find((c) => c.id === corpusId);
  const treeCorpusReason = !corpus
    ? "Select a corpus of text-layer PDFs."
    : corpus.source_ids.length > 10 ||
        corpus.source_ids.some(
          (id) => sources.find((s) => s.id === id)?.metadata.format !== "pdf",
        )
      ? "PageIndex requires a corpus containing only text-layer PDFs (up to 10)."
      : null;
  const selectedConfigs = selected
    .map((id) => configs.find((c) => c.id === id))
    .filter((c): c is Configuration => !!c);
  const closeInspector = useCallback(() => setInspection(null), []);
  const load = useCallback(async () => {
    const [s, c, f] = await Promise.all([
      apiAll<Source>(`/projects/${project}/sources`),
      apiAll<Corpus>(`/projects/${project}/corpus-versions`),
      apiAll<Configuration>(`/projects/${project}/configurations`),
    ]);
    setSources(s.items);
    setCorpora(c.items);
    setConfigs(f.items);
    setCorpusId((prior) => c.items.some((c) => c.id === prior) ? prior : c.items[0]?.id || "");
  }, [project]);
  useEffect(() => {
    load().catch((e) => setError(e.message)).finally(() => setWorkspaceLoading(false));
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
  }, [project, corpusId, run?.id]);
  useEffect(() => {
    const pending = Object.values(bundles).filter((b) =>
      ["queued", "preparing"].includes(b.status),
    );
    if (!sources.some((s) => s.status === "processing" || s.status === "deleting" && !s.error) && !pending.length)
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
      api<{ items: Run[]; next_cursor: string | null }>(
        `/projects/${project}/runs?q=${encodeURIComponent(historyQuery)}${historyStatus ? `&status=${historyStatus}` : ""}`,
      )
        .then((r) => { setHistory(r.items); setHistoryCursor(r.next_cursor); })
        .catch((e) => setError(e.message));
    }, 200);
    return () => clearTimeout(timer);
  }, [view, project, historyQuery, historyStatus]);
  useEffect(() => {
    if (!run) return;
    const controller = new AbortController();
    let state = emptyState(run.id);
    let attempts = 0;
    setDisconnected(false);
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
            const savedCursor = sessionStorage.getItem(
              `replay-cursor:${run!.id}`,
            );
            if (savedCursor !== null && !controller.signal.aborted) {
              const seq = Math.min(
                savedEvents.current.length,
                Math.max(0, Number(savedCursor) || 0),
              );
              setCursor(seq);
              setReplaying(true);
              setPlayback(await replay(run!.id, savedEvents.current, seq));
            }
            return;
          }
        } catch (e) {
          if (controller.signal.aborted) return;
          setConnected(false);
          if (++attempts >= 5) {
            setError((e as Error).message);
            setDisconnected(true);
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
  }, [run?.id, connectionAttempt]);
  async function action(work: () => Promise<void>, task = "working") {
    setBusyTask(task);
    setError("");
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyTask("");
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
    }, "upload");
  }
  async function freezeCorpus() {
    if (sourceSelectionError) {
      setError(sourceSelectionError);
      return;
    }
    await action(async () => {
      const c = await post<Corpus>(`/projects/${project}/corpus-versions`, {
        source_ids: selectedSources,
      });
      setCorpusId(c.id);
      await load();
      onView("playground");
    }, "corpus");
  }
  async function addTechnique(capability: Capability) {
    const defaultConfig = capability.default_config;
    if (!defaultConfig || !modelsReady || selected.length >= 6) return;
    await action(async () => {
      const cfg = await post<Configuration>(
        `/projects/${project}/configurations`,
        { name: capability.display_name, config: applyModelDefaults(defaultConfig, modelSelection) },
      );
      setConfigs((prior) => [...prior, cfg]);
      setSelected((prior) => [...prior, cfg.id]);
    }, "technique");
  }
  async function prepare() {
    if (!modelsReady) return;
    await action(async () => {
      const created: Configuration[] = [];
      const reconciled: Configuration[] = [];
      for (const current of selectedConfigs) {
        const config = pipelineUsesModels(current.config, modelSelection)
          ? current
          : await post<Configuration>(`/projects/${project}/configurations`, {
              name: current.name,
              based_on_config_id: current.id,
              config: applyModelDefaults(current.config, modelSelection),
            });
        if (config !== current) created.push(config);
        reconciled.push(config);
      }
      if (created.length) setConfigs((prior) => [...prior, ...created]);
      setSelected(reconciled.map((config) => config.id));
      const next: Record<string, Bundle> = {};
      for (const config of reconciled) {
        if (bundles[config.id]?.status === "ready") {
          next[config.id] = bundles[config.id];
          continue;
        }
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
    }, "prepare");
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
      openRun(result);
    }, "run");
  }
  function openRun(next: Run) {
    sessionStorage.setItem(`bundles:${project}:${next.corpus_version_id}`, JSON.stringify(
      Object.fromEntries(next.lanes.map((lane) => [lane.config_id, lane.bundle_id])),
    ));
    setCorpusId(next.corpus_version_id);
    setSelected(next.lanes.map((lane) => lane.config_id));
    setQuestion(next.question);
    setSetupOpen(false);
    setMobileLane(0);
    setInspection(null);
    setRun(next);
  }
  async function seek(seq: number) {
    if (!run) return;
    const request = ++seekRequest.current;
    setFollowLane(null);
    setReplaying(true);
    let next = playback;
    if (replaying && next && seq >= next.lastSeq) {
      for (const event of events.slice(next.lastSeq, seq))
        next = await reduceEvent(next, event);
    } else next = await replay(run.id, events, seq);
    if (request !== seekRequest.current) return;
    setCursor(seq);
    setPlayback(next);
    sessionStorage.setItem(`replay-cursor:${run.id}`, String(seq));
  }
  const ready =
    !!corpus &&
    modelsReady &&
    selectedConfigs.length > 0 &&
    selectedConfigs.every(
      (c) =>
        pipelineUsesModels(c.config, modelSelection) &&
        bundles[c.id]?.status === "ready",
    );
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
        {workspaceLoading && <p role="status"><Loading label="Loading project workspace" /> Loading project workspace…</p>}
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
              <Button
                disabled={busy}
                onClick={() => setInspection({ kind: "postgres" })}
              >
                Connect PostgreSQL
              </Button>
              <label className={`button ${busy ? "disabled" : ""}`}>
                {busyTask === "upload" && <Loading label="Uploading files" />}
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
                  20 MiB per file · {MAX_CORPUS_SOURCES} sources per corpus · Scanned PDFs need a
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
                      disabled={source.status !== "ready"}
                      onClick={() => setInspection({ kind: "source", source })}
                    >
                      <strong>{source.display_name}</strong>
                      <span className="caption">
                        {source.metadata.format as string} ·{" "}
                        {formatBytes(source.size_bytes || 0)}
                      </span>
                      {source.error && (
                        <span className="error-text">
                          {source.error.message}
                        </span>
                      )}
                    </button>
                    <Status value={source.status} />
                    {source.status !== "deleted" && <Button tone="danger" aria-label={`Delete ${source.display_name}`} onClick={() => setInspection({ kind: "delete", source })}>{source.status === "deleting" ? "Retry cleanup" : "Delete"}</Button>}
                    {source.status === "processing" && source.job_id && <Button tone="danger" onClick={() => action(async () => { await post(`/jobs/${source.job_id}/cancel`, undefined); await load(); })}>Cancel</Button>}
                    {source.kind === "postgres" &&
                      source.status === "ready" && (
                        <Button
                          aria-label={`Refresh ${source.display_name}`}
                          onClick={() =>
                            setInspection({ kind: "postgres", source })
                          }
                        >
                          Refresh
                        </Button>
                      )}
                  </div>
                ))}
                {sourceSelectionError && <ErrorNotice message={sourceSelectionError} />}
                <div className="source-footer">
                  <span className="muted">
                    {selectedSources.length} / {MAX_CORPUS_SOURCES} selected · {formatBytes(selectedBytes)} / {formatBytes(MAX_CORPUS_BYTES)}
                  </span>
                  <Button
                    tone="primary"
                    loading={busyTask === "corpus"}
                    disabled={
                      busy ||
                      !!sourceSelectionError ||
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
              <label className="caption">Status<select value={historyStatus} onChange={(e) => setHistoryStatus(e.target.value)}><option value="">All statuses</option>{["completed", "partial", "failed", "cancelled", "queued", "running"].map((status) => <option value={status} key={status}>{status}</option>)}</select></label>
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
                      openRun(item);
                      onView("playground");
                    }}
                  >
                    <div>
                      <strong>{item.question}</strong>
                      <span className="caption">
                        {new Date(item.created_at).toLocaleString()} ·{" "}
                        {item.lanes.length} lanes · {item.mode === "live" ? "Live" : "Fixture"}
                      </span>
                    </div>
                    <Status value={item.status} />
                    <ChevronRight size={18} />
                  </button>
                ))}
                {historyCursor && <Button onClick={() => action(async () => {
                  const page = await api<{items: Run[]; next_cursor: string | null}>(`/projects/${project}/runs?q=${encodeURIComponent(historyQuery)}${historyStatus ? `&status=${historyStatus}` : ""}&cursor=${encodeURIComponent(historyCursor)}`);
                  setHistory((prior) => [...prior, ...page.items]); setHistoryCursor(page.next_cursor);
                })}>Load more comparisons</Button>}
              </div>
            )}
          </>
        ) : (
          <>
            <details className="comparison-setup" open={setupOpen} onToggle={(e) => setSetupOpen(e.currentTarget.open)}>
              <summary>Sources and pipelines <span className="caption">{corpus ? `Corpus ${corpus.ordinal}` : "Choose sources"} · {selectedConfigs.length} selected · {ready ? "Ready" : "Preparation required"}</span></summary>
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
                loading={busyTask === "prepare"}
                disabled={
                  busy || !modelsReady || !corpus || !selectedConfigs.length || ready || active
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
              {configs.length > 0 && <label>Use a saved configuration<select value="" disabled={active || selected.length >= 6} onChange={(e) => { if (e.target.value) setSelected((prior) => [...prior, e.target.value]); }}><option value="">Choose a saved revision…</option>{configs.map((c) => <option key={c.id} value={c.id} disabled={selected.includes(c.id)}>{c.name} · revision {c.revision}</option>)}</select></label>}
              {!modelsReady && <p className="caption">Check model access in Setup before adding a new pipeline.</p>}
              {busyTask === "technique" && <p className="caption"><Loading label="Adding technique" /> Adding technique…</p>}
              <div className="technique-grid">
                {capabilities.map((c) => (
                  <button
                    key={c.technique}
                    className="technique-option"
                    disabled={
                      !c.available ||
                      !modelsReady ||
                      (c.technique === "pageindex" && !!treeCorpusReason) ||
                      busy ||
                      selected.length >= 6 ||
                      active
                    }
                    onClick={() => addTechnique(c)}
                  >
                    <div>
                      <h3>{c.display_name}</h3>
                      <Plus size={16} />
                    </div>
                    <p>{c.description}</p>
                    {c.technique === "pageindex" && treeCorpusReason && (
                      <span className="caption">{treeCorpusReason}</span>
                    )}
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
            </details>
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
                  {run?.lanes[0]?.config_snapshot.generation.model
                    || modelSelection.generation?.models[0]
                    || "Choose an answer model in Setup."}
                </span>
                <Button
                  tone="primary"
                  type="submit"
                  loading={busyTask === "run"}
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
                {run.mode !== "live" && <p className="fixture-run caption">Saved fixture run · synthetic model responses</p>}
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
                            : disconnected ? "Connection interrupted" : "Reconnecting…"}{" "}
                      · Queue {ms(run.queue_ms)} · Timings describe this run
                    </span>
                  </div>
                  <Status value={playback?.status || run.status} />
                  {disconnected && <Button onClick={() => { setError(""); setConnectionAttempt((n) => n + 1); }}>Reconnect to saved events</Button>}
                  {active && (
                    <Button
                      tone="danger"
                      onClick={() =>
                        action(async () => {
                          await post(`/runs/${run.id}/cancel`, undefined);
                        })
                      }
                    >
                      Stop all
                    </Button>
                  )}
                </div>
                {terminal(run.status) && events.length > 0 && (
                  <div className="replay-bar">
                    <Button
                      onClick={async () => {
                        if (playing) {
                          setPlaying(false);
                          return;
                        }
                        if (!replaying || cursor >= events.length)
                          await seek(0);
                        setPlaying(true);
                      }}
                    >
                      {playing ? "Pause" : "Play replay"}
                    </Button>
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
                    <select
                      aria-label="Replay speed"
                      value={speed}
                      onChange={(e) => {
                        setSpeed(Number(e.target.value));
                        sessionStorage.setItem(
                          `replay-speed:${run.id}`,
                          e.target.value,
                        );
                      }}
                    >
                      {[0.5, 1, 2, 4].map((n) => (
                        <option key={n} value={n}>
                          {n}×
                        </option>
                      ))}
                    </select>
                    <label className="inline-check">
                      <input
                        type="checkbox"
                        checked={compressed}
                        onChange={(e) => setCompressed(e.target.checked)}
                      />
                      Compress long waits
                    </label>
                    <Button
                      onClick={async () => {
                        setPlaying(false);
                        seekRequest.current++;
                        setPlayback(await replay(run.id, events));
                        setReplaying(false);
                      }}
                    >
                      Show final answer
                    </Button>
                    <span className="caption replay-time">
                      {compressed ? "Compressed playback · " : ""}Recorded
                      elapsed:{" "}
                      {ms(
                        events[(replaying ? cursor : events.length) - 1]
                          ?.elapsed_ms,
                      )}
                    </span>
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
                            <LiveDuration
                              state={state}
                              elapsed={
                                events[(replaying ? cursor : events.length) - 1]
                                  ?.elapsed_ms || 0
                              }
                              connected={connected}
                              replaying={replaying}
                            />
                          </span>
                          <span>
                            First token{" "}
                            <strong>{ms(state?.metrics?.ttft_ms)}</strong>
                          </span>
                          {lane.status === "completed" && <Button onClick={() => setInspection({ kind: "export", lane, runId: run.id })}>Export</Button>}
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
                          {active && !replaying && !terminal(state?.status || "queued") && (
                            <Button
                              tone="danger"
                              onClick={() =>
                                action(async () => {
                                  await post(
                                    `/runs/${run.id}/lanes/${lane.id}/cancel`,
                                    undefined,
                                  );
                                })
                              }
                            >
                              Stop
                            </Button>
                          )}
                        </div>
                        <div
                          className="lane-tabs"
                          role="group"
                          aria-label="Lane view"
                        >
                          {["answer", "workflow", "evidence"].map((tab) => (
                            <button
                              key={tab}
                              aria-pressed={(tabs[lane.id] || "answer") === tab}
                              onClick={() =>
                                setTabs((prior) => ({
                                  ...prior,
                                  [lane.id]: tab,
                                }))
                              }
                            >
                              {tab}
                            </button>
                          ))}
                        </div>
                        {(tabs[lane.id] || "answer") === "answer" && (
                          <>
                            <div className="answer-text" onClick={(event) => {
                              const label = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-citation]")?.dataset.citation;
                              const evidence = state?.evidence.find((item) => item.label === label);
                              if (evidence) setInspection({ kind: "evidence", evidence });
                            }}>
                              {state?.answer ? (
                                <ReactMarkdown
                                  remarkPlugins={[remarkGfm]}
                                  components={answerComponents}
                                  urlTransform={(href) => href.startsWith("#evidence-") && state.evidence.some((e) => e.label === href.slice(10)) ? href : ""}
                                >
                                  {state.answer.replace(
                                    /\[(E[1-9][0-9]*)\]/g,
                                    "[$1](#evidence-$1)",
                                  )}
                                </ReactMarkdown>
                              ) : (
                                <p className="muted">
                                  {terminal(state?.status || "")
                                    ? "No answer text was recorded."
                                    : state?.status === "running"
                                    ? Object.values(state.stages).some((step) => step.name === "generation") ? "Waiting for first answer text…" : "Retrieving evidence…"
                                    : "Waiting for this lane."}
                                </p>
                              )}
                              {state?.error && (
                                <ErrorNotice message={state.error} />
                              )}
                            </div>
                          </>
                        )}
                        {(tabs[lane.id] || "answer") !== "workflow" && (
                          <div className="lane-evidence">
                            {state?.evidence.map((e) => (
                              <button
                                key={e.evidence_id}
                                onClick={() =>
                                  setInspection({
                                    kind: "evidence",
                                    evidence: e,
                                  })
                                }
                              >
                                <span>{e.label}</span>
                                {e.source_name}
                                <ChevronRight size={14} />
                              </button>
                            ))}
                          </div>
                        )}
                        {tabs[lane.id] === "workflow" && (
                          <Workflow
                            technique={lane.technique}
                            state={state}
                            selected={
                              inspection?.kind === "step" &&
                              inspection.laneId === lane.id
                                ? inspection.spanId
                                : undefined
                            }
                            follow={followLane === lane.id}
                            onFollow={() =>
                              setFollowLane((prior) =>
                                prior === lane.id ? null : lane.id,
                              )
                            }
                            onSelect={(spanId) =>
                              setInspection({
                                kind: "step",
                                laneId: lane.id,
                                spanId,
                              })
                            }
                          />
                        )}
                        {terminal(state?.status || "") && (
                          <div className="lane-actions">
                            <Button
                              onClick={() =>
                                action(async () => {
                                  openRun(
                                    await post<Run>(
                                      `/projects/${project}/runs`,
                                      {
                                        corpus_version_id:
                                          run.corpus_version_id,
                                        question: run.question,
                                        parent_run_id: run.id,
                                        lanes: [
                                          {
                                            config_id: lane.config_id,
                                            bundle_id: lane.bundle_id,
                                          },
                                        ],
                                      },
                                      true,
                                    ),
                                  );
                                })
                              }
                            >
                              Run this lane again
                            </Button>
                            <details>
                              <summary>Timing details</summary>
                              <dl>
                                {Object.entries(state?.metrics || {}).map(
                                  ([key, value]) => (
                                    <div key={key}>
                                      <dt>
                                        {key
                                          .replaceAll("_", " ")
                                          .replace(" ms", "")}
                                      </dt>
                                      <dd>{ms(value)}</dd>
                                    </div>
                                  ),
                                )}
                              </dl>
                            </details>
                          </div>
                        )}
                        {terminal(lane.status) && <LaneFeedback key={lane.id} runId={run.id} lane={lane} />}
                        {!!state?.warnings.length && (
                          <details className="lane-details" open>
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
                {terminal(run.status) && <RunPreference key={run.id} run={run} />}
              </>
            )}
          </>
        )}
      </div>
      {inspection && (
        <Inspector
          title={
            inspection.kind === "delete" ? "Delete source" : inspection.kind === "export" ? "Export implementation" : inspection.kind === "postgres"
              ? "PostgreSQL snapshot"
              : inspection.kind === "step"
                ? "Execution step"
                : inspection.kind === "settings"
                  ? "Pipeline settings"
                  : inspection.kind === "evidence"
                    ? "Source evidence"
                    : "Source preview"
          }
          onClose={closeInspector}
        >
          {inspection.kind === "delete" ? <DeleteSource source={inspection.source} onDeleted={async () => { setSelectedSources((ids) => ids.filter((id) => id !== inspection.source.id)); setRun(null); setSetupOpen(true); await load(); closeInspector(); }} /> : inspection.kind === "export" ? <ExportPanel key={inspection.lane.id} runId={inspection.runId} lane={inspection.lane} fixture={run?.mode !== "live"} /> : inspection.kind === "postgres" ? (
            <PostgresSource
              project={project}
              initial={inspection.source}
              onCaptured={(source) => {
                setSources((prior) => [...prior, source]);
                setSelectedSources((prior) => [...prior, source.id]);
              }}
              onReady={async (source) => {
                const previous = inspection.source;
                await load();
                if (previous && corpus?.source_ids.includes(previous.id)) {
                  const next = await post<Corpus>(
                    `/projects/${project}/corpus-versions`,
                    {
                      source_ids: corpus.source_ids.map((id) =>
                        id === previous.id ? source.id : id,
                      ),
                    },
                  );
                  setCorpusId(next.id);
                  setSelectedSources(next.source_ids);
                  await load();
                }
                closeInspector();
              }}
            />
          ) : inspection.kind === "settings" ? (
            <ConfigurationForm
              config={inspection.config}
              busy={busy}
              modelsReady={modelsReady}
              modelSelection={modelSelection}
              save={(config, alignGeneration) =>
                action(async () => {
                  const effective = applyModelDefaults(config, modelSelection);
                  const saved = await post<Configuration>(
                    `/projects/${project}/configurations`,
                    {
                      name: inspection.config.name,
                      config: effective,
                      based_on_config_id: inspection.config.id,
                    },
                  );
                  const aligned: Configuration[] = [];
                  const originals = selectedConfigs.filter((c) => c.id !== inspection.config.id);
                  if (alignGeneration) {
                    for (const other of originals) {
                      aligned.push(await post<Configuration>(`/projects/${project}/configurations`, {
                        name: other.name, based_on_config_id: other.id,
                        config: applyModelDefaults(
                          { ...other.config, generation: effective.generation },
                          modelSelection,
                        ),
                      }));
                    }
                  }
                  setConfigs((prior) => [...prior, saved, ...aligned]);
                  const replacements = new Map(aligned.map((c, i) => [originals[i].id, c.id]));
                  setSetupOpen(true);
                  setSelected((prior) =>
                    prior.map((id) =>
                      id === inspection.config.id ? saved.id : replacements.get(id) || id,
                    ),
                  );
                  setInspection({ kind: "settings", config: saved });
                }, "revision")
              }
            />
          ) : inspection.kind === "step" && run ? (
            <StepInspector
              runId={run.id}
              laneId={inspection.laneId}
              stages={playback?.lanes[inspection.laneId]?.stages}
              step={
                playback?.lanes[inspection.laneId]?.stages[inspection.spanId]
              }
              onEvidence={(evidence) =>
                setInspection({ kind: "evidence", evidence })
              }
            />
          ) : inspection.kind !== "step" ? (
            <SourceInspector inspection={inspection} />
          ) : null}
        </Inspector>
      )}
    </div>
  );
}

function SourceInspector({
  inspection,
}: {
  inspection: Extract<Inspection, { kind: "source" | "evidence" }>;
}) {
  const [preview, setPreview] = useState<components["schemas"]["SourcePreview"] | null>(null),
    [error, setError] = useState("");
  const evidence = inspection.kind === "evidence" ? inspection.evidence : null;
  const sourceId =
    evidence?.source_id ||
    (inspection.kind === "source" ? inspection.source.id : "");
  useEffect(() => {
    setPreview(null);
    setError("");
    const controller = new AbortController();
    const query = evidence
      ? `?start_char=${evidence.location.char_start || 0}&max_chars=12000`
      : "";
    api<components["schemas"]["SourcePreview"]>(`/sources/${sourceId}/content${query}`, { signal: controller.signal })
      .then(setPreview)
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
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
              : evidence.location.record_key
              ? `Record ${JSON.stringify(evidence.location.record_key)}`
              : `Lines ${evidence.location.line_start}–${evidence.location.line_end}`}
          </div>
          <p className="caption">
            {evidence.included_in_context
              ? "This exact passage was supplied to the answer model."
              : "This is a retrieved candidate. It was not recorded as supplied to the answer model."}
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
              {evidence.location.relation && <><dt>Relation</dt><dd>{evidence.location.relation}</dd></>}
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
      {inspection.kind === "source" && inspection.source.kind === "postgres" && <p className="caption">
        Frozen snapshot · captured {String(inspection.source.metadata.captured_at || "—")}
        {inspection.source.metadata.truncated ? " · Capture limit reached; this is a partial snapshot." : ""}
      </p>}
      <h3 className="spaced">Source text</h3>
      {error ? (
        <ErrorNotice message={error} />
      ) : (
        <pre className="source-preview">
          {preview?.content || "Loading source text…"}
        </pre>
      )}
      {preview && <p className="caption">Preview of this source location · characters {preview.location.char_start}–{preview.location.char_end}.{preview.truncated ? " More text is available in the original source." : " Other pages or records, if any, are in the original source."}</p>}
      <Button onClick={() => downloadFile(`/api/v1/sources/${sourceId}/file`, "source.txt").catch((e) => setError(e.message))}>Download original source</Button>
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
  modelsReady,
  modelSelection,
  save,
}: {
  config: Configuration;
  busy: boolean;
  modelsReady: boolean;
  modelSelection: ModelSelection;
  save: (config: Pipeline, align: boolean) => void;
}) {
  const [draft, setDraft] = useState<Pipeline>(structuredClone(config.config));
  const [align, setAlign] = useState(false);
  const valueAt = (path: string[]) => path.reduce((value, key) => (value as Record<string, unknown>)[key], draft as unknown);
  const update = (path: string[], value: unknown) => setDraft((prior) => {
    const next = structuredClone(prior);
    const parent = path.slice(0, -1).reduce((obj, key) => (obj as Record<string, unknown>)[key], next as unknown) as Record<string, unknown>;
    parent[path.at(-1)!] = value; return next;
  });
  const field = (path: string[], label: string, min: number, max: number, step = 1, nullable = false) => <label>{label}<input type="number" min={min} max={max} step={step} required={!nullable} value={valueAt(path) == null ? "" : Number(valueAt(path))} onChange={(e) => update(path, nullable && e.target.value === "" ? null : Number(e.target.value))} /></label>;
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
        save(applyModelDefaults(draft, modelSelection), align);
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
      <details><summary>Advanced retrieval settings</summary>
        {draft.search.bm25 && <>{field(["search","bm25","k1"], "BM25 term saturation (k1)", .1, 3, .1)}{field(["search","bm25","b"], "BM25 length normalization (b)", 0, 1, .05)}{field(["search","bm25","epsilon"], "BM25 epsilon", 0, 1, .05)}</>}
        {draft.embedding && <>
          <label>Document prefix<input value={draft.embedding.document_prefix} maxLength={200} onChange={(e) => update(["embedding","document_prefix"], e.target.value)} /></label>
          <label>Query prefix<input value={draft.embedding.query_prefix} maxLength={200} onChange={(e) => update(["embedding","query_prefix"], e.target.value)} /></label>
        </>}
        {draft.search.dense && <>
          <label>Vector search<select value={draft.search.dense.mode} onChange={(e) => update(["search","dense","mode"], e.target.value)}><option value="exact">Exact cosine search</option><option value="hnsw">HNSW approximate search</option></select></label>
          {draft.search.dense.mode === "hnsw" && field(["search","dense","hnsw_ef"], "HNSW search effort", 8, 1024, 1, true)}
          {field(["search","dense","min_score"], "Minimum cosine score (blank means no threshold)", -1, 1, .05, true)}
        </>}
        {draft.search.rrf && field(["search","rrf","k"], "Reciprocal rank fusion constant", 1, 1000)}
        {draft.parent && field(["parent","max_parent_tokens"], "Maximum parent tokens", 256, 4096)}
        {draft.reranker && <>{field(["reranker","max_input_tokens"], "Reranker scoring tokens", 64, 512)}<label>Reranker device<select value={draft.reranker.device} onChange={(e) => update(["reranker","device"], e.target.value)}><option value="cpu">CPU</option><option value="cuda">CUDA (requires available GPU)</option></select></label></>}
        {draft.tree && <>
          {field(["tree","max_documents"], "Maximum selected PDFs", 1, 3)}{field(["tree","max_depth"], "Tree depth limit", 1, 4)}{field(["tree","max_nodes"], "Tree node limit", 1, 12)}{field(["tree","max_calls"], "Tree model call limit", 1, 8)}{field(["tree","max_pages"], "Selected page limit", 1, 12)}
        </>}
        {field(["generation","seed"], "Answer seed (blank unless profile supports it)", 0, 2147483647, 1, true)}
        {field(["limits","lane_timeout_ms"], "Lane deadline (milliseconds)", 1000, 300000, 1000)}
      </details>
      <label className="inline-check"><input type="checkbox" checked={align} onChange={(e) => setAlign(e.target.checked)} /> Apply these answer settings to all selected lanes</label>
      <details>
        <summary>Full effective configuration</summary>
        <pre className="source-preview">
          {JSON.stringify(draft, null, 2)}
        </pre>
      </details>
      {!modelsReady && <p className="caption">Choose available models in Setup before saving a revision.</p>}
      <Button type="submit" tone="primary" disabled={busy || !modelsReady} loading={busy}>
        Save new revision
      </Button>
    </form>
  );
}
