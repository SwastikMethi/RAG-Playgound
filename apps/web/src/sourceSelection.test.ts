import { expect, it } from "vitest";
import {
  MAX_CORPUS_BYTES,
  formatBytes,
  selectedSourceBytes,
  sourceSelectionError,
} from "./sourceSelection";

it("totals selected source bytes and reports the existing corpus byte limit", () => {
  const sources = [
    { id: "one", size_bytes: 1.5 * 1024 * 1024 },
    { id: "two", size_bytes: 99 * 1024 * 1024 },
    { id: "ignored", size_bytes: 500 },
  ];
  const bytes = selectedSourceBytes(sources, ["one", "two"]);

  expect(bytes).toBe(100.5 * 1024 * 1024);
  expect(formatBytes(1.5 * 1024 * 1024)).toBe("1.5 MiB");
  expect(sourceSelectionError(2, bytes)).toBe(
    `Selected sources exceed the ${formatBytes(MAX_CORPUS_BYTES)} corpus limit. Deselect at least 512 KiB to continue.`,
  );
});
