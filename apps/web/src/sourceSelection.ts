export const MAX_CORPUS_SOURCES = 50;
export const MAX_CORPUS_BYTES = 100 * 1024 * 1024;

export function formatBytes(bytes: number) {
  const [unit, divisor] = bytes >= 1024 * 1024 ? ["MiB", 1024 * 1024] : bytes >= 1024 ? ["KiB", 1024] : ["B", 1];
  const value = bytes / divisor;
  return `${Number.isInteger(value) ? value : value.toFixed(1)} ${unit}`;
}

export function selectedSourceBytes(
  sources: Array<{ id: string; size_bytes?: number | null }>,
  selected: string[],
) {
  const ids = new Set(selected);
  return sources.reduce((total, source) => total + (ids.has(source.id) ? source.size_bytes || 0 : 0), 0);
}

export function sourceSelectionError(count: number, bytes: number) {
  if (count > MAX_CORPUS_SOURCES) {
    const excess = count - MAX_CORPUS_SOURCES;
    return `Select at most ${MAX_CORPUS_SOURCES} sources per corpus. Deselect ${excess} source${excess === 1 ? "" : "s"} to continue.`;
  }
  if (bytes > MAX_CORPUS_BYTES) {
    return `Selected sources exceed the ${formatBytes(MAX_CORPUS_BYTES)} corpus limit. Deselect at least ${formatBytes(bytes - MAX_CORPUS_BYTES)} to continue.`;
  }
  return "";
}
