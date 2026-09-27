import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BookOpen, FlaskConical, History, LogOut, Plus, Settings2 } from "lucide-react";
import {
  api,
  apiAll,
  hasToken,
  post,
  setToken,
  type Capability,
  type Project,
} from "./api";
import { Button, Empty, ErrorNotice } from "./ui";
import "./styles.css";
import { Workspace } from "./Workspace";
import { Setup } from "./Setup";

function App() {
  const [signedIn, signIn] = useState(hasToken());
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState("");
  const [mode, setMode] = useState("live");
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [name, setName] = useState("");
  const [view, setView] = useState<"playground" | "sources" | "history" | "setup">(
    "playground",
  );
  useEffect(() => {
    if (!signedIn) return;
    Promise.all([
      apiAll<Project>("/projects"),
      api<{ mode: string; items: Capability[] }>("/system/capabilities"),
    ])
      .then(([p, c]) => {
        setProjects(p.items);
        setProject(p.items[0]?.id || "");
        setMode(c.mode);
        setCapabilities(c.items);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [signedIn]);
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setToken(password);
    try {
      await api("/system/profiles");
      signIn(true);
      setPassword("");
    } catch (e) {
      setToken("");
      setError((e as Error).message);
    }
  }
  async function addProject(e: React.FormEvent) {
    e.preventDefault();
    const form = e.currentTarget as HTMLFormElement;
    try {
      const p = await post<Project>("/projects", { name });
      setProjects([...projects, p]);
      setProject(p.id);
      setName("");
      form.closest("details")?.removeAttribute("open");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (!signedIn)
    return (
      <main className="login">
        <div className="brand">
          <FlaskConical /> RAG Playground
        </div>
        <h1>
          Your documents.
          <br />
          Different ways to find answers.
        </h1>
        <p className="muted">A private workspace for exploring retrieval.</p>
        <form onSubmit={login}>
          <label>
            Application token
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <Button tone="primary" type="submit">
            Open workspace
          </Button>
        </form>
        {error && <ErrorNotice message={error} />}
        <p className="caption">The token stays in this browser session.</p>
      </main>
    );
  return (
    <div className="shell">
      <aside className="rail">
        <a className="brand" href="/">
          <FlaskConical size={22} />
          <span>
            RAG
            <br />
            Playground
          </span>
        </a>
        <label className="caption">
          <span>WORKSPACE</span>
          <select
            value={project}
            onChange={(e) => setProject(e.target.value)}
            aria-label="Project"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
            {!projects.length && <option value="">Create a project</option>}
          </select>
        </label>
        <nav>
          <button
            className={view === "playground" ? "active" : ""}
            onClick={() => setView("playground")}
          >
            <FlaskConical size={18} />
            Playground
          </button>
          <button
            className={view === "sources" ? "active" : ""}
            onClick={() => setView("sources")}
          >
            <BookOpen size={18} />
            Sources
          </button>
          <button
            className={view === "history" ? "active" : ""}
            onClick={() => setView("history")}
          >
            <History size={18} />
            History
          </button>
          <button className={view === "setup" ? "active" : ""} onClick={() => setView("setup")}><Settings2 size={18} />Setup</button>
        </nav>
        <details className="new-project">
          <summary>New project</summary>
          <form onSubmit={addProject}>
            <label>
              New project name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
                required
              />
            </label>
            <Button type="submit" aria-label="Create workspace project">
              Create project
            </Button>
          </form>
        </details>
        <Button
          onClick={() => {
            setToken("");
            signIn(false);
            setProjects([]);
          }}
        >
          <LogOut size={16} />
          Lock workspace
        </Button>
      </aside>
      <main className="workspace">
        <header className="page-heading">
          <div>
            <h1>{view === "playground" ? "Compare retrieval" : view === "sources" ? "Your sources" : view === "setup" ? "Workspace setup" : "Saved comparisons"}</h1>
            <p className="muted">
              Ask a question. Inspect its sources. Choose what works.
            </p>
          </div>
          <span className="caption">Private workspace</span>
        </header>
        {mode !== "live" && (
          <div className="notice">
            Fixture demonstration · synthetic model responses
          </div>
        )}
        {error && <ErrorNotice message={error} />}
        {view === "setup" ? <Setup /> : !project ? (
          <Empty title="Start with a project">
            <p>Keep a set of documents and comparisons together.</p>
            <form onSubmit={addProject} className="inline-form">
              <input
                aria-label="Project name"
                placeholder="e.g. Support knowledge"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
                required
              />
              <Button tone="primary" type="submit">
                <Plus size={16} />
                Create project
              </Button>
            </form>
          </Empty>
        ) : (
          <Workspace
            key={project}
            project={project}
            capabilities={capabilities}
            view={view}
            onView={setView}
          />
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
