import { useEffect, useRef, useState, type ReactNode } from "react";
import { FlaskConical } from "lucide-react";
import { api, post, setCSRF } from "./api";
import type { components } from "./generated/api";
import { Button, ErrorNotice } from "./ui";
import { ThemeToggle } from "./ThemeToggle";

export type CurrentAccount = components["schemas"]["CurrentAccount"];
type Recovery = components["schemas"]["AccountRecovery"];
type Session = components["schemas"]["AccountSession"];
type Turnstile = { render: (node: HTMLElement, options: Record<string, unknown>) => string; remove: (id: string) => void };
declare global { interface Window { turnstile?: Turnstile } }

function Challenge({ siteKey, action, onToken, attempt }: { siteKey: string; action: string; onToken: (token: string) => void; attempt: number }) {
  const element = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let id: string | undefined;
    const render = () => {
      if (!element.current || !window.turnstile || id) return;
      id = window.turnstile.render(element.current, { sitekey: siteKey, action, size: "flexible", callback: onToken,
        "expired-callback": () => onToken(""), "error-callback": () => { onToken(""); setFailed(true); } });
    };
    window.addEventListener("turnstile-ready", render);
    let script = document.querySelector<HTMLScriptElement>("script[data-turnstile]");
    if (!script) {
      script = document.createElement("script"); script.dataset.turnstile = "true";
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.onload = () => window.dispatchEvent(new Event("turnstile-ready"));
      script.onerror = () => setFailed(true);
      document.head.append(script);
    }
    render();
    return () => { window.removeEventListener("turnstile-ready", render); if (id) window.turnstile?.remove(id); };
  }, [siteKey, action, onToken, attempt]);
  return <><div ref={element} className="security-check" />{failed && <ErrorNotice message="The security check could not load. Reload this page to try again." />}</>;
}

export function AccountGate({ children }: { children: (account: CurrentAccount) => ReactNode }) {
  const [account, setAccount] = useState<CurrentAccount | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<CurrentAccount>("/auth/me").then(value => {
      setCSRF(value.csrf_token);
      const authPage = ["/login", "/signup", "/recover"].includes(location.pathname);
      if (value.deployment === "hosted" && !value.user && !authPage) { location.replace("/login"); return; }
      if (value.deployment === "local" && authPage) { location.replace("/"); return; }
      setAccount(value);
    }).catch(e => setError(e.message));
  }, []);
  if (error) return <main className="auth-shell"><ErrorNotice message={error} /><Button onClick={() => location.reload()}>Try again</Button></main>;
  if (!account) return <main className="auth-shell" role="status">Opening your workspace…</main>;
  if (["/login", "/signup", "/recover"].includes(location.pathname)) return <AuthScreen account={account} />;
  return children(account);
}

function AuthScreen({ account }: { account: CurrentAccount }) {
  const action = location.pathname === "/signup" ? "register" : location.pathname === "/recover" ? "recover" : "login";
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [token, setToken] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [recovery, setRecovery] = useState<Recovery | null>(null);
  const [saved, setSaved] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await post<Recovery | Session>(`/auth/${action}`, { username: name, password,
        turnstile_token: token, ...(action === "recover" ? { recovery_code: code } : {}) });
      setPassword(""); setCode(""); setCSRF(result.csrf_token);
      if ("recovery_code" in result) setRecovery(result);
      else location.replace("/"); // Full navigation removes authentication-only scripts.
    } catch (e) { setError((e as Error).message); setToken(""); setAttempt(value => value + 1); }
    finally { setBusy(false); }
  }
  return <main className="auth-shell">
    <div className="auth-top"><a href="/" className="auth-brand"><FlaskConical size={24} /> RAG Playground</a><ThemeToggle /></div>
    <section className="auth-card">
      {recovery ? <>
        <span className="caption">ACCOUNT RECOVERY</span>
        <h1>Save your recovery code</h1>
        <p>Store this code in your password manager for <strong>{recovery.user.username}</strong>. It is shown once and can reset your password.</p>
        <code className="recovery-code">{recovery.recovery_code}</code>
        <p className="muted">There is no email reset. Losing both your password and this code means losing access to your account.</p>
        <label className="check-row"><input type="checkbox" checked={saved} onChange={e => setSaved(e.target.checked)} />I saved my recovery code</label>
        <Button tone="primary" disabled={!saved} onClick={() => location.replace("/")}>Continue to workspace</Button>
      </> : <>
        <span className="caption">YOUR PRIVATE WORKSPACE</span>
        <h1>{action === "register" ? "Create your account" : action === "recover" ? "Recover your account" : "Sign in to your workspace"}</h1>
        <p className="muted">{action === "register" ? "Compare retrieval techniques with your documents and your own OpenAI key." : action === "recover" ? "Use your saved recovery code to set a new password." : "Your documents, comparisons and saved runs are waiting for you."}</p>
        {error && <ErrorNotice message={error} />}
        <form className="account-form" onSubmit={submit}>
          <label>Username<input autoComplete="username" autoCapitalize="none" spellCheck={false} required minLength={3} maxLength={32} value={name} onChange={e => setName(e.target.value)} /></label>
          {action === "recover" && <label>Recovery code<input autoComplete="off" required maxLength={128} value={code} onChange={e => setCode(e.target.value)} /></label>}
          <label>{action === "recover" ? "New password" : "Password"}<input type="password" autoComplete={action === "login" ? "current-password" : "new-password"} required minLength={action === "login" ? 1 : 15} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
          {action !== "login" && <p className="caption">Use a passphrase of 15–128 characters.</p>}
          <Challenge siteKey={account.turnstile_site_key || ""} action={action} onToken={setToken} attempt={attempt} />
          <Button tone="primary" type="submit" disabled={busy || !token}>{busy ? "Please wait…" : action === "register" ? "Create account" : action === "recover" ? "Reset password" : "Sign in"}</Button>
        </form>
        <nav className="auth-links" aria-label="Account access">
          {action !== "login" && <a href="/login">Sign in</a>}
          {action !== "register" && <a href="/signup">Create an account</a>}
          {action !== "recover" && <a href="/recover">Recover your account</a>}
        </nav>
      </>}
    </section>
    <p className="auth-footnote">Documents remain private to your account. Model requests use your OpenAI account and are billed by OpenAI.</p>
  </main>;
}

export function AccountSettings({ onKeyChanged }: { onKeyChanged: () => void }) {
  const [key, setKey] = useState("");
  const [configured, setConfigured] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  useEffect(() => { api<{configured:boolean}>("/me/openai-key").then(v => setConfigured(v.configured)).catch(e => setError(e.message)); }, []);
  async function changeKey(remove = false) {
    setBusy(true); setError(""); setMessage("");
    try {
      await api("/me/openai-key", {method: remove ? "DELETE" : "PUT", ...(remove ? {} : {body: JSON.stringify({api_key:key})})});
      setKey(""); setConfigured(!remove); onKeyChanged();
      setMessage(remove ? "Key removed. New model jobs need a key." : "Key saved securely. Model access is checked when you prepare or ask a question.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function changePassword(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const result = await post<Session>("/auth/password", {current_password:current, password});
      setCSRF(result.csrf_token); setCurrent(""); setPassword(""); setMessage("Password changed. Other sessions have been signed out.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="account-settings">
    <h2>Your OpenAI key</h2>
    <p className="muted">{configured ? "A key is saved for your account." : "Add your key before preparing indexes or asking questions."} Keys are encrypted on this server and never included in exports.</p>
    {error && <ErrorNotice message={error} />}{message && <p role="status">{message}</p>}
    <form className="account-form" onSubmit={e => {e.preventDefault(); void changeKey();}}>
      <label>OpenAI API key<input type="password" autoComplete="off" spellCheck={false} required minLength={10} maxLength={512} value={key} onChange={e => setKey(e.target.value)} /></label>
      <div className="account-actions"><Button tone="primary" type="submit" disabled={busy}>{configured ? "Replace key" : "Save key"}</Button>{configured && <Button type="button" disabled={busy} onClick={() => void changeKey(true)}>Remove key</Button>}</div>
    </form>
    <p className="caption">Changes apply when a job starts. Already-running provider requests may still be billed. Revoke a compromised key in your OpenAI account.</p>
    <details className="password-settings"><summary>Change password</summary>
      <form className="account-form" onSubmit={changePassword}>
        <label>Current password<input type="password" autoComplete="current-password" required maxLength={128} value={current} onChange={e => setCurrent(e.target.value)} /></label>
        <label>New password<input type="password" autoComplete="new-password" required minLength={15} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <Button type="submit" disabled={busy}>Update password</Button>
      </form>
    </details>
  </section>;
}
