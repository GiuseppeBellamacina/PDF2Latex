import { File, FileText, Globe, X } from "lucide-react";
import type { ProgressEvent } from "../../hooks/useGenerateWs";
import {
  COLORS,
  NODE_ICONS,
  statusBadge,
  type GraphState,
  type NodeDetail,
} from "../PipelineGraph.utils";
import { cn, getDocumentSourceColor, getResearchSourceStyle } from "../../lib/utils";

interface Props {
  selectedNode: string;
  nodeDetail: NodeDetail;
  graphState: GraphState;
  events: ProgressEvent[];
  onClose: () => void;
}

export default function NodeDetailPanel({
  selectedNode,
  nodeDetail,
  graphState,
  events,
  onClose,
}: Props) {
  const levelHex =
    nodeDetail.level === "error"
      ? COLORS.level.error
      : nodeDetail.level === "warning"
        ? COLORS.level.warning
        : nodeDetail.level === "success"
          ? COLORS.level.success
          : COLORS.level.info;

  return (
    <div className="card space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span
            className="rounded-lg p-1.5"
            style={{
              backgroundColor: statusBadge(nodeDetail.status).color + "18",
              color: statusBadge(nodeDetail.status).color,
            }}
          >
            <svg
              width={16}
              height={16}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path d={NODE_ICONS[selectedNode] ?? ""} />
            </svg>
          </span>
          <div>
            <h3 className="text-sm font-semibold">{nodeDetail.title}</h3>
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{
                backgroundColor:
                  statusBadge(nodeDetail.status).color + "18",
                color: statusBadge(nodeDetail.status).color,
              }}
            >
              {statusBadge(nodeDetail.status).label}
            </span>
          </div>
        </div>
        <button
          className="rounded-md p-1 text-ink-400 hover:text-ink-700 hover:bg-ink-100 dark:hover:bg-ink-800"
          onClick={onClose}
          aria-label="Close detail panel"
        >
          <X size={16} />
        </button>
      </div>

      {/* Divider */}
      <div
        className="h-0.5 w-full rounded-full"
        style={{ backgroundColor: levelHex + "30" }}
      />

      {/* Detail lines */}
      <div className="space-y-1.5">
        {nodeDetail.lines.map((line, i) => {
          const isSection = line.startsWith("  ");
          return (
            <div
              key={i}
              className={`text-sm leading-relaxed ${
                isSection
                  ? "ml-2 text-ink-500 dark:text-ink-400"
                  : "text-ink-700 dark:text-ink-300 font-medium"
              }`}
            >
              {line.trimStart()}
            </div>
          );
        })}
      </div>

      {/* Rich: Research sources */}
      {nodeDetail.researchSources && nodeDetail.researchSources.length > 0 && (
        <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
          <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
            Sources found ({nodeDetail.researchSources.length})
          </p>
          <div className="max-h-48 space-y-1.5 overflow-y-auto">
            {nodeDetail.researchSources.map((src, i) => {
              const sourceStyle = getResearchSourceStyle(src.source ?? "");
              return (
                <div
                  key={i}
                  className="flex items-start gap-2 rounded-md bg-ink-50/50 px-2.5 py-1.5 dark:bg-ink-800/50"
                >
                  <span className={cn("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded", sourceStyle.color)}>
                    {sourceStyle.icon}
                  </span>
                  <span className="text-sm leading-snug text-ink-700 dark:text-ink-300">
                    {src.title.length > 80 ? src.title.slice(0, 79) + "…" : src.title}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Rich: Analyzed documents */}
      {nodeDetail.analyzeDocuments && nodeDetail.analyzeDocuments.length > 0 && (
        <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
          <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
            Documents analyzed ({nodeDetail.analyzeDocuments.length})
          </p>
          <div className="space-y-1">
            {nodeDetail.analyzeDocuments.map((doc, i) => {
              const lower = doc.toLowerCase();
              let DocIcon = File;
              if (lower.endsWith(".pdf")) DocIcon = File;
              else if (lower.endsWith(".md") || lower.endsWith(".txt")) DocIcon = FileText;
              else if (lower.includes("://") || lower.startsWith("http")) DocIcon = Globe;
              return (
              <div key={i} className="flex items-center gap-2 px-2 py-1 text-sm text-ink-700 dark:text-ink-300">
                <DocIcon size={12} className={`shrink-0 ${getDocumentSourceColor(doc)}`} />
                <span>{doc.length > 60 ? doc.slice(0, 59) + "…" : doc}</span>
              </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Rich: Chapter details (progress bars) */}
      {nodeDetail.chapterDetails && nodeDetail.chapterDetails.length > 0 && (
        <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
          <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
            Chapters ({nodeDetail.chapterDetails.length})
          </p>
          <div className="space-y-2">
            {nodeDetail.chapterDetails.map((ch, i) => {
              const pct = ch.total > 0 ? Math.round((ch.done / ch.total) * 100) : 0;
              return (
                <div key={i}>
                  <div className="mb-0.5 flex items-center justify-between text-xs">
                    <span className="truncate font-medium text-ink-700 dark:text-ink-300">
                      {ch.name.length > 28 ? ch.name.slice(0, 27) + "…" : ch.name}
                    </span>
                    <span className="ml-2 shrink-0 tabular-nums text-ink-400">
                      {ch.done}/{ch.total}
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-200 dark:bg-ink-700">
                    <div
                      className="h-full rounded-full bg-emerald-500 transition-all duration-700"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Rich: Error detail (LaTeX log) */}
      {nodeDetail.errorDetail && (
        <div className="rounded-lg border border-red-200/60 p-3 dark:border-red-900/60">
          <p className="mb-2 text-xs font-medium text-red-500 dark:text-red-400 uppercase">
            LaTeX Error
          </p>
          <div className="max-h-48 overflow-y-auto rounded-lg bg-red-50/80 p-2.5 font-mono text-[11px] leading-relaxed text-red-800 dark:bg-red-950/60 dark:text-red-200">
            {nodeDetail.errorDetail.split("\n").slice(0, 6).map((line, i) => (
              <div key={i}>{line || "\u00A0"}</div>
            ))}
            {nodeDetail.errorDetail.split("\n").length > 6 && (
              <div className="mt-1 text-red-400 dark:text-red-500">
                … +{nodeDetail.errorDetail.split("\n").length - 6} lines
              </div>
            )}
          </div>
        </div>
      )}

      {/* Extra: Write node — chapter details (fallback from graphState) */}
      {selectedNode === "write" && graphState.chapters.length > 0 && !nodeDetail.chapterDetails && (
        <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
          <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
            Chapter details
          </p>
          <div className="space-y-2">
            {graphState.chapters.map((ch) => {
              const prog = graphState.chapterProgress[ch.name];
              const done = prog?.done ?? 0;
              const total = prog?.total ?? ch.sections;
              const pct =
                total > 0 ? Math.round((done / total) * 100) : 0;
              return (
                <div key={ch.name}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium text-ink-700 dark:text-ink-300">
                      {ch.name}
                    </span>
                    <span className="tabular-nums text-ink-400">
                      {done}/{total} sections ({pct}%)
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${pct}%`,
                      backgroundColor:
                        done === total && total > 0
                          ? COLORS.chapter.done.stroke
                          : COLORS.chapter.active.stroke,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Extra: Plan node — full structure */}
      {selectedNode === "plan" &&
        (() => {
          const planEvent = events.find(
            (e) => e.node === "plan" && e.plan,
          );
          if (!planEvent?.plan) return null;
          return (
            <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
              <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
                Full structure ({planEvent.plan.length} sections)
              </p>
              <ol className="space-y-1 text-sm text-ink-600 dark:text-ink-400">
                {planEvent.plan.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="shrink-0 tabular-nums text-ink-400">
                      {i + 1}.
                    </span>
                    <span>
                      <span className="font-medium text-ink-700 dark:text-ink-300">
                        {s.part_title}
                      </span>
                      {" — "}
                      {s.title}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          );
        })()}

      {/* Extra: Review node — compilation log */}
      {selectedNode === "review" &&
        (() => {
          const reviewEvents = events.filter(
            (e) => e.node === "review",
          );
          if (!reviewEvents.length) return null;
          return (
            <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
              <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
                Compilation log ({reviewEvents.length} event
                {reviewEvents.length !== 1 ? "s" : ""})
              </p>
              <div className="max-h-48 overflow-y-auto rounded bg-ink-50 p-2 font-mono text-[11px] leading-relaxed dark:bg-ink-950">
                {reviewEvents.map((e, i) => (
                  <div
                    key={i}
                    className={
                      e.level === "error"
                        ? "text-red-600 dark:text-red-400"
                        : e.level === "warning"
                          ? "text-amber-600 dark:text-amber-400"
                          : e.level === "success"
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-ink-500"
                    }
                  >
                    <span className="text-ink-400">
                      [{e.stage}]
                    </span>{" "}
                    {e.message}
                    {e.detail && (
                      <span className="text-ink-400">
                        {" "}
                        — {e.detail}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })()}
    </div>
  );
}
