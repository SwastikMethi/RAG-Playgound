import type { components } from "./generated/api";
export type Project = components["schemas"]["Project"];
export type Capability = components["schemas"]["Capability"];
export type Configuration = components["schemas"]["Configuration"];
export type Source = components["schemas"]["Source"];
export type Corpus = components["schemas"]["Corpus"];
export type Run = components["schemas"]["Run"];
export type Lane = components["schemas"]["Lane"];
export type Bundle = components["schemas"]["IndexBundle"];
export type Pipeline = Configuration["config"];
export type Job = components["schemas"]["Job"];
let csrf: string | null = null;
export function setCSRF(value: string | null) { csrf = value; }
export function requireSession(response: Response) {
  if (response.status === 401 && !["/login", "/signup", "/recover"].includes(location.pathname)) location.replace("/login");
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers: {
      ...(csrf && options.method && !["GET", "HEAD"].includes(options.method) ? { "X-CSRF-Token": csrf } : {}),
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    if (!path.startsWith("/auth/")) requireSession(response);
    const value = await response.json().catch(() => null);
    throw new Error(
      value?.error?.message ? `${value.error.message}${value.error.details?.field ? ` Field: ${value.error.details.field}.` : ""}` : `Request failed (${response.status}).`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export function post<T>(path: string, body: unknown, idempotent = false) {
  return api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: idempotent ? { "Idempotency-Key": crypto.randomUUID() } : {},
  });
}

export async function apiAll<T>(path: string): Promise<{ items: T[] }> {
  // ponytail: owner-sized pickers load all records; virtualize if their measured size becomes costly.
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    const page: { items: T[]; next_cursor: string | null } = await api(`${path}?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return { items };
}

export async function downloadFile(path: string, filename: string) {
  const response = await fetch(path);
  requireSession(response);
  if (!response.ok) throw new Error("Download failed. Check that the file is still available.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = response.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1] || filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
