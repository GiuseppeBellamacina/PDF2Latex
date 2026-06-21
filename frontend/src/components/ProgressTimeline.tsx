import {
  BookOpenCheck,
  BookOpenText,
  Check,
  FileSearch,
  Gavel,
  GitMerge,
  ListTree,
  Loader2,
  Microscope,
  PencilLine,
  ScanText,
  Wrench,
} from "lucide-react";
import { type ProgressEvent } from "../hooks/useGenerateWs";
import { cn } from "../lib/utils";
import { COLORS, deriveState } from "./PipelineGraph.utils";

const STAGES = [
  { key: "extracting", label: "Extraction", icon: ScanText },
  { key: "analyzing", label: "Analysis", icon: FileSearch },
  { key: "planning", label: "Planning", icon: ListTree },
  { key: "writing", label: "Writing", icon: PencilLine },
  { key: "overview", label: "Overview", icon: BookOpenText },
  { key: "coherence", label: "Coherence", icon: Microscope },
  { key: "citations", label: "Citations", icon: BookOpenCheck },
  { key: "merge", label: "Merge", icon: GitMerge },
  { key: "reviewing", label: "Review", icon: Wrench },
  { key: "judging", label: "Judge", icon: Gavel },
  { key: "done", label: "Completed", icon: Check },
];

interface Props {
  events: ProgressEvent[];
  latest: ProgressEvent | null;
  onNodeClick?: (nodeId: string) => void;
  selectedNode?: string | null;
}

export default function ProgressTimeline({ events, latest, onNodeClick, selectedNode }: Props) {
  const currentStage = latest?.stage ?? "";
  const currentIdx = STAGES.findIndex((s) => s.key === currentStage);
  const progress = latest?.progress ?? 0;
  const failed = currentStage === "error";
  const completed = currentStage === "done";

  // Pipeline node heatmap — compressed state bar below the main progress bar.
  const NODE_ORDER = [
    "extract", "research", "analyze", "merge_analyses", "plan", "write",
    "overview", "coherence", "citations", "merge", "review", "judge",
  ];
  const NODE_LABELS: Record<string, string> = {
    extract: "Extract", research: "Research", analyze: "Analyze",
    merge_analyses: "Merge Sources", plan: "Plan", write: "Write",
    overview: "Overview", coherence: "Coherence", citations: "Citations",
    merge: "Merge", review: "Review", judge: "Judge",
  };
  const graphState = deriveState(events);

  function nodeColor(state: string): string {
    switch (state) {
      case "completed": return COLORS.edgeCompleted.from;
      case "active": return COLORS.node.active.stroke;
      case "error": return COLORS.level.error;
      default: return COLORS.node.pending.stroke;
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex items-center justify-between text-xs text-ink-500">
          <span className="flex items-center gap-1.5">
            {!completed && !failed && currentIdx >= 0 && (
              <Loader2 size={12} className="animate-spin text-ink-400" />
            )}
            {latest?.message ?? "Waiting…"}
          </span>
          <span className="tabular-nums">{progress}%</span>
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

        {/* Node state heatmap */}
        <div className="mt-1.5 flex gap-[3px]">
          {NODE_ORDER.map((nid) => {
            const state = graphState.nodes[nid] ?? "pending";
            const active = graphState.activeNodes.has(nid);
            const displayState = state === "pending" && active ? "active" : state;
            const clickable = displayState !== "pending" && onNodeClick;
            const isSelected = selectedNode === nid;
            return (
              <div
                key={nid}
                className={cn(
                  "h-1.5 flex-1 rounded-sm transition-all duration-300",
                  isSelected && "ring-2 ring-white dark:ring-ink-900 shadow-sm",
                )}
                style={{
                  backgroundColor: nodeColor(displayState),
                  cursor: clickable ? "pointer" : "default",
                }}
                title={`${NODE_LABELS[nid]}: ${displayState}${clickable ? " — click for details" : ""}`}
                onClick={() => clickable && onNodeClick?.(nid)}
              />
            );
          })}
        </div>
      </div>

      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {STAGES.map((s, i) => {
          const active = i === currentIdx && !completed;
          const done = (currentIdx > i && currentIdx >= 0) || completed;
          const Icon = s.icon;
          return (
            <li
              key={s.key}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors",
                done
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                  : active
                    ? "border-ink-500 bg-ink-100 text-ink-900 dark:bg-ink-800/40 dark:text-ink-100"
                    : "border-ink-200 text-ink-400 dark:border-ink-800",
              )}
            >
              {active ? (
                <Loader2 size={14} className="shrink-0 animate-spin" />
              ) : done ? (
                <Check
                  size={14}
                  className="shrink-0 text-emerald-600 dark:text-emerald-400"
                />
              ) : (
                <Icon size={14} className="shrink-0" />
              )}
              <span className="truncate">{s.label}</span>
            </li>
          );
        })}
      </ol>

      <div className="max-h-56 overflow-auto rounded-lg border border-ink-200 bg-ink-50 p-3 font-mono text-xs dark:border-ink-800 dark:bg-ink-950">
        {events.length === 0 ? (
          <p className="text-ink-400">No events.</p>
        ) : (
          events.map((e, i) => {
            const level = e.level ?? "info";
            const color =
              level === "error"
                ? "text-red-600 dark:text-red-400"
                : level === "warning"
                  ? "text-amber-600 dark:text-amber-400"
                  : level === "success"
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-ink-600 dark:text-ink-400";
            return (
              <div key={i} className={color}>
                <span className="text-ink-400">[{e.stage}]</span> {e.message}
                {e.detail && (
                  <span className="text-ink-400"> — {e.detail}</span>
                )}
              </div>
            );
          })
        )}
      </div>

      {latest?.tokens && latest.tokens.total_tokens > 0 && (
        <p className="text-xs text-ink-400">
          Token: {latest.tokens.total_tokens.toLocaleString()} (
          {latest.tokens.input_tokens.toLocaleString()} in /{" "}
          {latest.tokens.output_tokens.toLocaleString()} out) ·{" "}
          {latest.tokens.calls} LLM calls
        </p>
      )}
    </div>
  );
}
