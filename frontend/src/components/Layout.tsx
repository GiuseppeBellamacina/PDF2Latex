import { FileText, History, Settings, Upload } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { cn } from "../lib/utils";
import ThemeToggle from "./ThemeToggle";

const nav = [
  { to: "/", label: "Nuovo", icon: Upload, end: true },
  { to: "/history", label: "Archivio", icon: History, end: false },
  { to: "/settings", label: "Provider", icon: Settings, end: false },
];

export default function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b border-ink-200 bg-ink-50/80 backdrop-blur dark:border-ink-800 dark:bg-ink-950/80">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <div className="flex items-center gap-2 font-semibold tracking-tight">
            <FileText size={18} />
            <span>PDF2LaTeX</span>
          </div>
          <nav className="flex items-center gap-1">
            {nav.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "btn-ghost border-transparent",
                    isActive &&
                      "bg-ink-200 text-ink-900 dark:bg-ink-800 dark:text-ink-100",
                  )
                }
              >
                <Icon size={15} />
                <span className="hidden sm:inline">{label}</span>
              </NavLink>
            ))}
            <ThemeToggle />
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
