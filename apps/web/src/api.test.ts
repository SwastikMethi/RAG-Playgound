import { expect, it, vi } from "vitest";
import { api } from "./api";

it("hashes JSON request bodies for the private Lambda origin", async () => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetcher);

  await api("/example", { method: "POST", body: '{"x":1}' });

  expect(fetcher.mock.calls[0][1]?.headers).toMatchObject({
    "x-amz-content-sha256": "5041bf1f713df204784353e82f6a4a535931cb64f1f4b4a5aeaffcb720918b22",
  });
  vi.unstubAllGlobals();
});

it("serializes and hashes multipart request bodies for the private Lambda origin", async () => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetcher);
  const form = new FormData();
  form.append("file", new Blob(["demo"]), "demo.txt");

  await api("/upload", { method: "POST", body: form });

  const init = fetcher.mock.calls[0][1]!;
  const body = init.body as ArrayBuffer;
  const expected = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", body)),
    (byte) => byte.toString(16).padStart(2, "0")).join("");
  expect(body).toBeInstanceOf(ArrayBuffer);
  expect(init.headers).toMatchObject({ "x-amz-content-sha256": expected });
  expect((init.headers as Record<string, string>)["content-type"]).toMatch(/^multipart\/form-data; boundary=/);
  vi.unstubAllGlobals();
});
