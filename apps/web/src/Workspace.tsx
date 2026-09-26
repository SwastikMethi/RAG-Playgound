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
import { Workflow, StepInspector, LiveDuration } from "./Workflow";

type View = "playground" | "sources" | "history";
type Inspection =
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
                      !c.available ||
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
                          {!terminal(state?.status || "queued") && (
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
                            <div className="answer-text">
                              {state?.answer ? (
                                <ReactMarkdown
                                  remarkPlugins={[remarkGfm]}
                                  components={{
                                    img: () => null,
                                    a: ({ href, children }) =>
                                      href?.startsWith("#evidence-") &&
                                      state.evidence.some(
                                        (e) => e.label === href.slice(10),
                                      ) ? (
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
                                  setRun(
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
            inspection.kind === "step"
              ? "Execution step"
              : inspection.kind === "settings"
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
          ) : inspection.kind === "step" && run ? (
            <StepInspector
              runId={run.id}
              laneId={inspection.laneId}
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
  inspection: Exclude<Inspection, { kind: "settings" | "step" }>;
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
