import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type ButtonHTMLAttributes,
} from "react";
import { X } from "lucide-react";

export function Button({
  children,
  tone = "neutral",
  loading = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "primary" | "neutral" | "danger";
  loading?: boolean;
}) {
  return (
    <button
      {...props}
      disabled={loading || props.disabled}
      aria-busy={loading || undefined}
      className={`button ${tone} ${props.className || ""}`}
    >
      {loading && <Loading />}
      {children}
    </button>
  );
}
export function Loading({ label = "Loading" }: { label?: string }) {
  return <span className="loading-indicator" role="status" aria-label={label} />;
}
export function BackgroundWork({ status }: { status: "queued" | "preparing" }) {
  const message =
    status === "queued"
      ? "Starting the on-demand worker or waiting for earlier work. This may take about a minute after inactivity."
      : "Preparing selected pipelines…";
  return (
    <span className="background-work caption">
      <Loading label={message} />
      {message}
    </span>
  );
}
export function Status({ value }: { value: string }) {
  const active = ["queued", "processing", "preparing", "running", "building"].includes(value);
  return (
    <span className={`status ${value}`} aria-busy={active || undefined}>
      <span aria-hidden="true" />
      {value.replaceAll("_", " ")}
    </span>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <div className="muted">{children}</div>
    </div>
  );
}
export function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="notice error" role="alert">
      {message}
    </div>
  );
}
export function Inspector({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [modal, setModal] = useState(window.matchMedia("(max-width: 1100px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1100px)");
    const change = () => setModal(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const regions = modal ? [...document.querySelectorAll<HTMLElement>(".rail, .page-heading, .workspace-content")] : [];
    const inert = regions.map((node) => node.inert);
    regions.forEach((node) => node.inert = true);
    root.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (modal && e.key === "Tab") {
        const nodes = [...(root.current?.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,a[href],[tabindex='0']") || [])].filter((n) => n.getClientRects().length);
        const first = nodes[0], last = nodes.at(-1);
        if (e.shiftKey && (document.activeElement === first || document.activeElement === root.current)) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      regions.forEach((node, i) => node.inert = inert[i]);
      previous?.focus();
    };
  }, [onClose, modal]);
  return (
    <aside ref={root} tabIndex={-1} className="inspector" aria-label={title} role={modal ? "dialog" : "complementary"} aria-modal={modal || undefined}>
      <header>
        <h2>{title}</h2>
        <Button aria-label="Close inspector" onClick={onClose}>
          <X size={18} />
        </Button>
      </header>
      <div className="inspector-body">{children}</div>
    </aside>
  );
}
