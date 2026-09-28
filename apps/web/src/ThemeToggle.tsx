import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "./ui";
import { applyTheme, type Theme } from "./theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light"
  );
  const next = theme === "dark" ? "light" : "dark";
  return <Button className="theme-toggle" aria-label={`Use ${next} mode`} onClick={() => {
    setTheme(next);
    applyTheme(next);
    try { localStorage.setItem("rag-theme", next); } catch { /* Browser storage is optional. */ }
  }}>
    {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
    <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
  </Button>;
}
