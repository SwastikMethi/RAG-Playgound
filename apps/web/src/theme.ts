export type Theme = "light" | "dark";

export function resolveTheme(saved: string | null, prefersDark: boolean): Theme {
  return saved === "light" || saved === "dark" ? saved : prefersDark ? "dark" : "light";
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}
