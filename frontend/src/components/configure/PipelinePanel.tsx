import { useCallback, useMemo, useRef, useState } from "react";
import { Layers, Microscope, Sparkles, Zap } from "lucide-react";
import PipelineBuilder from "../PipelineBuilder";
import SourceReorder from "../SourceReorder";
import type { Source } from "../../lib/api";

const PRESETS: { label: string; icon: typeof Zap; desc: string; config: Record<string, string> }[] = [
  {
    label: "Fast",
    icon: Zap,
    desc: "PyMuPDF text + figures only. Fastest extraction.",
    config: { text: "pymupdf", structure: "none", ocr: "none", math: "none", figures: "pymupdf", figure_scoring: "heuristic" },
  },
  {
    label: "Recommended",
    icon: Sparkles,
    desc: "Docling structure + PyMuPDF figures + OCR fallback.",
    config: { text: "pymupdf", structure: "docling", ocr: "tesseract", math: "none", figures: "pymupdf", figure_scoring: "heuristic" },
  },
  {
    label: "Scientific",
    icon: Microscope,
    desc: "Recommended + Nougat math recovery. Best for papers.",
    config: { text: "pymupdf", structure: "docling", ocr: "tesseract", math: "nougat", figures: "pymupdf", figure_scoring: "heuristic" },
  },
];

interface Props {
  projectId: string;
  pipelineConfig: Record<string, string>;
  setPipelineConfig: (v: Record<string, string>) => void;
  orderedSources: Source[];
  setOrderedSources: (v: Source[]) => void;
}

export default function PipelinePanel({
  projectId,
  pipelineConfig,
  setPipelineConfig,
  orderedSources,
  setOrderedSources,
}: Props) {
  const [animatingPreset, setAnimatingPreset] = useState<string | null>(null);
  const pipelineRef = useRef<HTMLDivElement>(null);

  const flashPipeline = useCallback(() => {
    const el = pipelineRef.current;
    if (!el) return;
    el.classList.remove("animate-pipeline-flash");
    void el.offsetWidth;
    el.classList.add("animate-pipeline-flash");
  }, []);

  const applyPreset = useCallback(
    (label: string, config: Record<string, string>) => {
      setAnimatingPreset(label);
      setPipelineConfig({ ...pipelineConfig, ...config });
      flashPipeline();
    },
    [flashPipeline, setPipelineConfig, pipelineConfig],
  );

  const activeTools = useMemo(
    () => Object.entries(pipelineConfig).filter(([, v]) => v && v !== "none").map(([k, v]) => `${k}:${v}`),
    [pipelineConfig],
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2.5">
        <span className="rounded-lg bg-ink-100 p-1.5 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
          <Layers size={16} />
        </span>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">Extraction Pipeline</h2>
      </div>

      {/* Presets */}
      <div>
        <p className="mb-3 text-xs text-ink-500">
          Pick a preset or customize each stage below. Disabled tools are not installed — the install command is shown.
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {PRESETS.map((preset) => {
            const isActive = Object.keys(preset.config).every((k) => pipelineConfig[k] === preset.config[k]);
            const isAnim = animatingPreset === preset.label;
            return (
              <button
                key={preset.label}
                type="button"
                onClick={() => applyPreset(preset.label, preset.config)}
                className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-all duration-200 ${
                  isActive
                    ? "border-emerald-400 bg-emerald-50/40 shadow-sm dark:bg-emerald-900/20"
                    : "border-ink-200/60 hover:border-ink-400 hover:bg-ink-50/40 dark:border-ink-700/60 dark:hover:bg-ink-800/40"
                } ${isAnim ? "animate-preset-glow" : ""}`}
              >
                <span
                  onAnimationEnd={() => setAnimatingPreset(null)}
                  className={`mt-0.5 shrink-0 rounded-lg p-1.5 transition-colors duration-200 ${
                    isActive ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400" : "bg-ink-100 text-ink-500 dark:bg-ink-800"
                  } ${isAnim ? "animate-preset-pop" : ""}`}
                >
                  <preset.icon size={16} />
                </span>
                <div className="min-w-0 text-left">
                  <p className="text-sm font-semibold">{preset.label}</p>
                  <p className="text-xs text-ink-500">{preset.desc}</p>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Active tools summary pills */}
      <div className="flex flex-wrap items-center gap-1.5">
        {activeTools.map((t) => (
          <span key={t} className="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] text-ink-600 dark:bg-ink-800 dark:text-ink-400">
            {t}
          </span>
        ))}
      </div>

      {/* Pipeline builder with collapsible stages */}
      <div ref={pipelineRef} className="border-t border-ink-200/60 pt-4 dark:border-ink-700/60">
        <PipelineBuilder
          projectKey={projectId}
          value={pipelineConfig}
          onChange={setPipelineConfig}
        />
      </div>

      {/* Source order */}
      <div className="border-t border-ink-200/60 pt-5 dark:border-ink-700/60">
        <h3 className="mb-3 text-sm font-medium">PDF extraction order</h3>
        <p className="mb-3 text-xs text-ink-500">
          Drag rows to reorder — this determines how contents are merged into the final document.
        </p>
        <SourceReorder sources={orderedSources} onReorder={setOrderedSources} />
      </div>
    </div>
  );
}
