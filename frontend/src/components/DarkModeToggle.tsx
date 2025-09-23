import { useEffect, useState } from "react";
import { MoonStar, Sun } from "lucide-react";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";

type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "theme";

const getStoredTheme = (): Theme => {
  if (typeof window === "undefined") {
    return "light";
  }
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return stored === "dark" || stored === "light" ? stored : "light";
};

const applyTheme = (theme: Theme) => {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.style.setProperty("color-scheme", theme);
};

const DarkModeToggle = () => {
  const [theme, setTheme] = useState<Theme>(() => getStoredTheme());

  useEffect(() => {
    applyTheme(theme);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme((current) => (current === "light" ? "dark" : "light"));
  };

  const isDark = theme === "dark";

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      aria-pressed={isDark}
      aria-label={isDark ? "Dark Mode aktiv" : "Light Mode aktiv"}
      className="relative text-navbar-foreground"
    >
      <Sun
        className={cn(
          "h-5 w-5 transition-all",
          isDark ? "rotate-90 scale-0" : "rotate-0 scale-100"
        )}
      />
      <MoonStar
        className={cn(
          "absolute h-5 w-5 transition-all",
          isDark ? "rotate-0 scale-100" : "rotate-90 scale-0"
        )}
      />
      <span className="sr-only">Farbschema wechseln</span>
    </Button>
  );
};

export default DarkModeToggle;
