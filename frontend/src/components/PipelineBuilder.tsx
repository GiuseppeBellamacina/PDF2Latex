import { Cpu, Info, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type PipelineDescription } from "../lib/api";

interface Props {
  projectKey: string;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}

/**
 * Composable extraction pipeline dashboard.
 *
 * Renders one card per stage (text, structure, OCR, math, figures, figure
 * scoring). Each stage exposes its mutually-exclusive tools as radio options,
 * with an inline explanation of what every tool does. Tools that are not
 * installed are disabled and show the exact `uv sync` command needed to enable
 * them, so the user never picks two tools that do the same job.
 */
export default function PipelineBuilder({
  projectKey,
  value,
  onChange,
}: Props) {
  const [desc, setDesc] = useState<PipelineDescription | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getPipeline(projectKey)
      .then(setDesc)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Pipeline not available"),
      );
  }, [projectKey]);

  function selected(stageId: string, fallback: string): string {
    return value[stageId] ?? fallback;
  }

  function pick(stageId: string, toolId: string) {
    onChange({ ...value, [stageId]: toolId });
  }

  if (error) {
    return <p className="text-sm text-red-500">{error}</p>;
  }

  if (!desc) {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-500">
        <Loader2 size={16} className="animate-spin" /> Loading pipeline…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 rounded-lg bg-ink-50/40 p-3 text-xs text-ink-500 dark:bg-ink-800/40">
        <Info size={14} className="mt-0.5 shrink-0" />
        <span>
          Build your own extraction pipeline. Each stage runs exactly one tool;
          optional stages can be turned off. Disabled tools are not installed —
          run the suggested command to enable them. This overrides the legacy
          backend selection above.
        </span>
      </div>

      {desc.stages.map((stage) => {
        const current = selected(stage.id, stage.selected);
        return (
          <div
            key={stage.id}
            className="rounded-xl border border-ink-200/60 p-4 dark:border-ink-700/60"
          >
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold">{stage.label}</h3>
              {stage.optional ? (
                <span className="text-[11px] uppercase tracking-wide text-ink-400">
                  optional
                </span>
              ) : (
                <span className="text-[11px] uppercase tracking-wide text-ink-400">
                  required
                </span>
              )}
            </div>
            <p className="mb-3 text-xs text-ink-500">{stage.description}</p>

            <div className="space-y-2">
              {stage.tools.map((tool) => {
                const disabled = !tool.available && tool.id !== "none";
                const isSelected = current === tool.id;
                return (
                  <label
                    key={tool.id}
                    className={[
                      "flex cursor-pointer gap-3 rounded-lg border p-3 transition",
                      isSelected
                        ? "border-emerald-400 bg-emerald-50/40 dark:bg-emerald-900/20"
                        : "border-ink-200/60 dark:border-ink-700/60",
                      disabled ? "cursor-not-allowed opacity-60" : "",
                    ].join(" ")}
                  >
                    <input
                      type="radio"
                      className="mt-1"
                      name={`stage-${stage.id}`}
                      checked={isSelected}
                      disabled={disabled}
                      onChange={() => pick(stage.id, tool.id)}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">
                          {tool.label}
                        </span>
                        {tool.gpu ? (
                          <span className="inline-flex items-center gap-1 rounded bg-indigo-500/10 px-1.5 py-0.5 text-[10px] font-medium text-indigo-500">
                            <Cpu size={11} /> GPU
                          </span>
                        ) : null}
                        {!tool.available && tool.id !== "none" ? (
                          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-500">
                            not installed
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-0.5 text-xs text-ink-500">
                        {tool.description}
                      </p>
                      {disabled && tool.install ? (
                        <code className="mt-1 block w-full overflow-x-auto rounded bg-ink-900/90 px-2 py-1 text-[11px] text-ink-100">
                          {tool.install}
                        </code>
                      ) : null}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
