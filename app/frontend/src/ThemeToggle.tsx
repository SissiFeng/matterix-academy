import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import s from "./ThemeToggle.module.css";

type Theme = "system" | "light" | "dark";
const KEY = "lab.theme";

function stored(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // Private windows may block storage; the choice still applies to this tab.
  }
}

const options: { value: Theme; label: string; Icon: typeof Sun }[] = [
  { value: "system", label: "Match system", Icon: Monitor },
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
];

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(stored);
  useEffect(() => apply(theme), [theme]);
  return (
    <div className={s.track} role="group" aria-label="Color theme">
      {options.map(({ value, label, Icon }) => (
        <button
          key={value}
          aria-pressed={theme === value}
          aria-label={label}
          title={label}
          className={theme === value ? s.active : undefined}
          onClick={() => setTheme(value)}
        >
          <Icon size={14} />
        </button>
      ))}
    </div>
  );
}
