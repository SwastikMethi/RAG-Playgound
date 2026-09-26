import { headers } from "./api";
import type { TraceEvent } from "./reducer";

export async function streamEvents(
  runId: string,
  after: number,
  onEvent: (event: TraceEvent) => Promise<void>,
  signal: AbortSignal,
) {
  const response = await fetch(
    `/api/v1/runs/${runId}/events?after_seq=${after}`,
    { headers: headers(), signal },
  );
  if (!response.ok)
    throw new Error(
      response.status === 401
        ? "The application token has expired. Lock and reopen the workspace."
        : "The event stream is unavailable.",
    );
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder
        .decode(value, { stream: !done })
        .replaceAll("\r\n", "\n");
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) await onEvent(JSON.parse(data));
      }
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
