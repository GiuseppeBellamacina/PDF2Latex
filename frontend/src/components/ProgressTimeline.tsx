import { Check } from "lucide-react";
import { type ProgressEvent } from "../hooks/useGenerateWs";
import { cn } from "../lib/utils";

const STAGES = [
  { key: "extracting", label: "Estrazione" },
  { key: "analyzing", label: "Analisi" },
  { key: "planning", label: "Pianificazione" },
  { key: "writing", label: "Scrittura" },
  { key: "reviewing", label: "Revisione" },
  { key: "done", label: "Completato" },
];

interface Props {
  events: ProgressEvent[];
  latest: ProgressEvent | null;
}

export default function ProgressTimeline({ events, latest }: Props) {
  const currentStage = latest?.stage ?? "";
  const currentIdx = STAGES.findIndex((s) => s.key === currentStage);
  const progress = latest?.progress ?? 0;
  const failed = currentStage === "error";
  const completed = currentStage === "done";

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex items-center justify-between text-xs text-ink-500">
          <span>{latest?.message ?? "In attesa…"}</span>
          <span>{progress}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              failed
                ? "bg-red-500"
                : completed
                  ? "bg-emerald-500"
                  : "bg-ink-900 dark:bg-ink-100",
            )}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {STAGES.map((s, i) => {
          const active = i === currentIdx && !completed;
          const done = currentIdx > i || completed;
          return (
            <li
              key={s.key}
              className={cn(
                "flex items-center justify-between rounded-lg border px-3 py-2 text-xs transition-colors",
                done
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                  : active
                    ? "border-ink-500 text-ink-900 dark:text-ink-100"
                    : "border-ink-200 text-ink-400 dark:border-ink-800",
              )}
            >
              <span>{s.label}</span>
              {done && (
                <Check
                  size={14}
                  className="text-emerald-600 dark:text-emerald-400"
                />
              )}
            </li>
          );
        })}
      </ol>

      <div className="max-h-56 overflow-auto rounded-lg border border-ink-200 bg-ink-50 p-3 font-mono text-xs dark:border-ink-800 dark:bg-ink-950">
        {events.length === 0 ? (
          <p className="text-ink-400">Nessun evento.</p>
        ) : (
          events.map((e, i) => (
            <div key={i} className="text-ink-600 dark:text-ink-400">
              <span className="text-ink-400">[{e.stage}]</span> {e.message}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
