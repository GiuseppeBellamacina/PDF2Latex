import {
  ChevronDown,
  Cpu,
  FileText,
  Image,
  Loader2,
  ScanText,
  Sigma,
  Table,
  Target,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, type PipelineDescription } from "../lib/api";

interface Props {
  projectKey: string;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}

const STAGE_ICONS: Record<string, typeof FileText> = {
  text: FileText,
  structure: Table,
  ocr: ScanText,
  math: Sigma,
  figures: Image,
  figure_scoring: Target,
};

/**
 * Composable extraction pipeline dashboard.
 *
 * Each stage is collapsible: click the header to show/hide the tool grid.
 * A continuous timeline line runs on the left, connecting all stages.
 * The collapsed header shows a summary of the currently selected tool.
 */
export default function PipelineBuilder({
  projectKey,
  value,
  onChange,
}: Props) {
  const [desc, setDesc] = useState<PipelineDescription | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["text"]));

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

  function toggleStage(stageId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(stageId)) next.delete(stageId);
      else next.add(stageId);
      return next;
    });
  }

  /** Find the label of the currently selected tool for a stage. */
  function selectedLabel(stageId: string, fallback: string): string {
    const stage = desc?.stages.find((s) => s.id === stageId);
    if (!stage) return fallback;
    const toolId = selected(stageId, fallback);
    if (toolId === "none") return "Skipped";
    const tool = stage.tools.find((t) => t.id === toolId);
    return tool?.label ?? toolId;
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
    <div className="space-y-0">
      {desc.stages.map((stage, idx) => {
        const current = selected(stage.id, stage.selected);
        const isOff = stage.optional && current === "none";
        const open = expanded.has(stage.id);
        const isLast = idx === desc.stages.length - 1;
        const Icon = STAGE_ICONS[stage.id] ?? FileText;

        return (
          <div key={stage.id} className="relative flex gap-3">
            {/* Timeline connector */}
            <div className="flex shrink-0 flex-col items-center">
              {/* Node dot */}
              <div
                className={`z-10 mt-5 flex h-7 w-7 items-center justify-center rounded-full border-2 transition-colors ${
                  isOff
                    ? "border-ink-200 bg-ink-100 text-ink-400 dark:border-ink-700 dark:bg-ink-800 dark:text-ink-600"
                    : "border-emerald-400 bg-white text-emerald-600 shadow-sm dark:border-emerald-700 dark:bg-ink-900 dark:text-emerald-400"
                }`}
              >
                <Icon size={12} />
              </div>
              {/* Vertical line */}
              {!isLast && (
                <div className="flex-1 min-h-[16px] w-0 border-l-2 border-dashed border-ink-200/70 dark:border-ink-700/70" />
              )}
            </div>

            {/* Stage card */}
            <div className="min-w-0 flex-1 pb-4">
              <button
                type="button"
                onClick={() => toggleStage(stage.id)}
                aria-expanded={open}
                className={`w-full rounded-xl border p-3 text-left transition-all ${
                  isOff
                    ? "border-ink-200/30 bg-ink-50/20 opacity-50 dark:border-ink-700/30 dark:bg-ink-900/10"
                    : "border-ink-200/60 bg-white hover:border-ink-400 dark:border-ink-700/60 dark:bg-ink-950 dark:hover:border-ink-600"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <h3 className="text-sm font-semibold">{stage.label}</h3>
                      <div className="flex items-center gap-2">
                        {/* Pill: selected tool name (visible when collapsed) */}
                        {!open && (
                          <span className="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] text-ink-500 dark:bg-ink-800 dark:text-ink-400">
                            {selectedLabel(stage.id, stage.selected)}
                          </span>
                        )}
                        {/* Required / Optional pill */}
                        {stage.optional ? (
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                              isOff
                                ? "bg-ink-100 text-ink-400 dark:bg-ink-800 dark:text-ink-500"
                                : "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                            }`}
                          >
                            {isOff ? "off" : "on"}
                          </span>
                        ) : (
                          <span className="rounded-full bg-ink-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-500 dark:bg-ink-800">
                            required
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="mt-1 text-xs text-ink-500">
                      {stage.description}
                    </p>
                  </div>
                  {/* Chevron */}
                  <ChevronDown
                    size={18}
                    aria-hidden="true"
                    className={`mt-0.5 shrink-0 text-ink-400 transition-transform duration-200 ${
                      open ? "rotate-180" : ""
                    }`}
                  />
                </div>
              </button>

              {/* Expandable tool grid */}
              {open && (
                <div className="mt-2 grid grid-cols-2 gap-2 pl-0">
                  {stage.optional && (
                    <label
                      className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2.5 transition-all ${
                        current === "none"
                          ? "border-emerald-400 bg-emerald-50/40 shadow-sm dark:bg-emerald-900/20"
                          : "border-ink-200/40 hover:border-ink-300 dark:border-ink-700/40 dark:hover:border-ink-600"
                      }`}
                    >
                      <input
                        type="radio"
                        className="shrink-0"
                        name={`stage-${stage.id}`}
                        checked={current === "none"}
                        onChange={() => pick(stage.id, "none")}
                      />
                      <span className="text-xs font-medium text-ink-400">
                        Skip this stage
                      </span>
                    </label>
                  )}

                  {stage.tools.map((tool) => {
                    const disabled = !tool.available && tool.id !== "none";
                    const isSelected = current === tool.id;
                    return (
                      <label
                        key={tool.id}
                        className={`group flex cursor-pointer gap-3 rounded-lg border p-3 transition-all ${
                          isSelected
                            ? "border-emerald-400 bg-emerald-50/40 shadow-sm dark:bg-emerald-900/20"
                            : "border-ink-200/40 hover:border-ink-400 hover:bg-ink-50/30 dark:border-ink-700/40 dark:hover:border-ink-600 dark:hover:bg-ink-800/20"
                        } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
                      >
                        <input
                          type="radio"
                          className="mt-0.5 shrink-0"
                          name={`stage-${stage.id}`}
                          checked={isSelected}
                          disabled={disabled}
                          onChange={() => pick(stage.id, tool.id)}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
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
                            {isSelected && (
                              <span className="ml-auto rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                                selected
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-xs leading-relaxed text-ink-500">
                            {tool.description}
                          </p>
                          {disabled && tool.install ? (
                            <code className="mt-2 block w-full overflow-x-auto rounded bg-ink-900/90 px-2 py-1 text-[11px] text-ink-100">
                              {tool.install}
                            </code>
                          ) : null}
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
