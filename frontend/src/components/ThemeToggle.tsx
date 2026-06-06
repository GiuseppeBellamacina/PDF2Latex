import { Moon, Sun } from "lucide-react";
import { useTheme } from "../hooks/useTheme";

export default function ThemeToggle() {
  const { dark, toggle } = useTheme();
  return (
    <button
      onClick={toggle}
      className="btn-ghost h-9 w-9 p-0"
      aria-label="Toggle theme"
      title={dark ? "Light theme" : "Dark theme"}
    >
      {dark ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
