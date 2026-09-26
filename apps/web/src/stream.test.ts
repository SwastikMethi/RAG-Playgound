import { it, expect, vi } from "vitest";
import { streamEvents } from "./stream";
it("resumes from the supplied cursor and handles CRLF and Unicode split across bytes", async () => {
  vi.stubGlobal("sessionStorage", { getItem: () => "" });
  const data = new TextEncoder().encode(
    'data: {"text":"🪐"}\r\n\r\n: heartbeat\r\n\r\n',
  );
  const fetcher = vi.fn(
    async (_url: string, _options?: RequestInit) =>
      new Response(
        new ReadableStream({
          start(c) {
            for (const byte of data) c.enqueue(new Uint8Array([byte]));
            c.close();
          },
        }),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const events: unknown[] = [];
  await streamEvents(
    "run",
    4,
    async (e) => {
      events.push(e);
    },
    new AbortController().signal,
  );
  expect(fetcher.mock.calls[0][0]).toContain("after_seq=4");
  expect(events).toEqual([{ text: "🪐" }]);
  vi.unstubAllGlobals();
});
