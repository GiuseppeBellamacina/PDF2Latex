import { X } from "lucide-react";
import type { Provider } from "../../lib/api";
import ProviderSelect from "../ProviderSelect";

interface RoleProvider {
  provider_id: number;
  model?: string;
}

interface Props {
  providers: Provider[];
  roleProviders: Record<string, RoleProvider>;
  setRoleProviders: React.Dispatch<
    React.SetStateAction<Record<string, RoleProvider>>
  >;
  running: boolean;
}

const ROLES = [
  { key: "analyzer", label: "Analyzer", desc: "Analizza il contenuto dei documenti" },
  { key: "researcher", label: "Researcher", desc: "Ricerca web e sintesi" },
  { key: "planner", label: "Planner", desc: "Pianifica la struttura del documento" },
  { key: "writer", label: "Writer", desc: "Scrive le sezioni LaTeX" },
  { key: "reviewer", label: "Reviewer", desc: "Corregge errori di compilazione" },
  { key: "judge", label: "Judge", desc: "Valuta qualità e struttura finale" },
  { key: "coherence", label: "Coherence", desc: "Verifica coerenza tra capitoli" },
  { key: "citations", label: "Citations", desc: "Audit citazioni e bibliografia" },
  { key: "overview", label: "Overview", desc: "Genera la panoramica iniziale" },
];

export default function RoleProviderGrid({
  providers,
  roleProviders,
  setRoleProviders,
  running,
}: Props) {
  return (
    <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
      {ROLES.map((role) => {
        const selected = roleProviders[role.key];
        return (
          <div
            key={role.key}
            className={`rounded-lg border p-3 transition-colors ${
              selected
                ? "border-indigo-300 bg-indigo-50/50 dark:border-indigo-700 dark:bg-indigo-950/30"
                : "border-ink-200/60 bg-white dark:border-ink-800/60 dark:bg-ink-900/30"
            }`}
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold text-ink-700 dark:text-ink-300">
                {role.label}
              </span>
              {selected && (
                <button
                  type="button"
                  className="rounded p-0.5 text-ink-400 hover:text-ink-600 hover:bg-ink-100 dark:hover:bg-ink-800"
                  onClick={() => {
                    const next = { ...roleProviders };
                    delete next[role.key];
                    setRoleProviders(next);
                  }}
                  title="Rimuovi assegnazione"
                >
                  <X size={12} />
                </button>
              )}
            </div>
            <p className="mb-2 text-[10px] leading-tight text-ink-400">
              {role.desc}
            </p>
            <ProviderSelect
              providers={providers}
              value={selected?.provider_id ?? null}
              onChange={(pid) => {
                if (pid == null) {
                  const next = { ...roleProviders };
                  delete next[role.key];
                  setRoleProviders(next);
                } else {
                  setRoleProviders({
                    ...roleProviders,
                    [role.key]: {
                      provider_id: pid,
                      model:
                        providers.find((p) => p.id === pid)
                          ?.default_model ?? undefined,
                    },
                  });
                }
              }}
              disabled={running}
              placeholder="— usa provider principale —"
              small
            />
            {selected && (
              <input
                type="text"
                className="input mt-1.5 w-full text-xs py-1.5"
                placeholder="Model (default del provider)"
                value={selected.model ?? ""}
                onChange={(e) =>
                  setRoleProviders({
                    ...roleProviders,
                    [role.key]: {
                      ...selected,
                      model: e.target.value || undefined,
                    },
                  })
                }
                disabled={running}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
