import { useMemo, useState } from "react";
import type { ProgressEvent } from "../hooks/useGenerateWs";
import {
  CHAPTER_H,
  CHAPTER_ROW_H,
  CHAPTER_START_Y,
  CHAPTER_W,
  CENTER_Y,
  COLORS,
  EDGES,
  MAIN_NODES,
  NODE_H,
  NODE_ICONS,
  NODE_W,
  POS,
  ROW_SPREAD,
  chapterX,
  cx,
  cy,
  deriveNodeDetails,
  derivePhaseInfo,
  deriveState,
  edgePath,
  loopbackPath,
  statusBadge,
  x0,
  y0,
} from "./PipelineGraph.utils";

/* ── Helpers ────────────────────────────────────────────────────────────── */

/** Clip long text for tooltip display */
function ellipsis(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

/* ── Component ──────────────────────────────────────────────────────────── */

interface Props {
  events: ProgressEvent[];
  onNodeClick?: (nodeId: string) => void;
}

export default function PipelineGraph({ events, onNodeClick }: Props) {
  const state = useMemo(() => deriveState(events), [events]);
  const phaseInfo = useMemo(() => derivePhaseInfo(state), [state]);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const nodeDetail = hoveredNode
    ? deriveNodeDetails(hoveredNode, events, state)
    : null;

  // SVG dimensions: accommodate the rightmost node (judge, col 8).
  const svgW = cx(8) + NODE_W / 2 + 40;
  const chapterCount = state.chapters.length;
  const chaptersHeight =
    chapterCount > 0
      ? CHAPTER_START_Y + chapterCount * CHAPTER_ROW_H + 30 - CENTER_Y
      : 0;
  // Discover actual max row among main nodes (citations at row=1 needs room)
  const maxRow = Math.max(...MAIN_NODES.map((n) => n.row));
  const nodeAreaH = CENTER_Y + maxRow * ROW_SPREAD + NODE_H / 2 + 80;
  const svgH = Math.max(
    nodeAreaH,
    CENTER_Y + chaptersHeight + 60,
  );

  // Compute node-level progress bar colour
  const progressColor =
    phaseInfo.progress === 100
      ? "bg-emerald-500"
      : state.errorNode
        ? "bg-red-500"
        : "bg-emerald-500";

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-200/60 bg-gradient-to-br from-ink-50 via-white to-ink-50 p-4 dark:border-ink-800/60 dark:from-ink-950 dark:via-ink-900 dark:to-ink-950">
      {/* ── Phase indicator header ─────────────────────────────────── */}
      {phaseInfo.activeNodeIds.length > 0 || phaseInfo.completedCount > 0 ? (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          {/* Phase name + icon */}
          <div className="flex items-center gap-2">
            {phaseInfo.currentIcon && (
              <svg
                width={18}
                height={18}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                className="text-emerald-600 dark:text-emerald-400"
              >
                <path d={phaseInfo.currentIcon} />
              </svg>
            )}
            <span className="text-sm font-semibold text-ink-800 dark:text-ink-200">
              <span className="text-ink-400 font-normal">Phase </span>
              {phaseInfo.phaseIndex}
              <span className="text-ink-400 font-normal"> of {phaseInfo.totalPhases}</span>
              <span className="mx-1.5 text-ink-300 dark:text-ink-600">·</span>
              <span className="phase-gradient-text">{phaseInfo.currentPhase}</span>
            </span>
          </div>

          {/* Step count badge */}
          {state.errorNode && (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-medium text-red-700 dark:bg-red-900/40 dark:text-red-300">
              <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                <path d="M12 9v4m0 4h.01" />
              </svg>
              Error at {phaseInfo.currentPhase}
            </span>
          )}

          {state.judgeRevising && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
              <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
              Revision requested
            </span>
          )}

          {/* Spacer */}
          <div className="ml-auto hidden sm:block" />

          {/* Global progress bar */}
          <div className="flex items-center gap-2 sm:ml-auto">
            <div className="h-1.5 w-28 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
              <div
                className={`h-full rounded-full transition-all duration-1000 ease-out ${progressColor} ${
                  phaseInfo.progress > 0 && phaseInfo.progress < 100
                    ? "animate-progress-shimmer"
                    : ""
                }`}
                style={{ width: `${Math.max(phaseInfo.progress, 4)}%` }}
              />
            </div>
            <span className="text-[11px] font-medium tabular-nums text-ink-500 dark:text-ink-400">
              {phaseInfo.completedCount}/{phaseInfo.totalCount}
            </span>
          </div>
        </div>
      ) : null}

      <svg
        viewBox={`0 0 ${svgW} ${svgH}`}
        className="w-full min-w-[1200px]"
        style={{ fontFamily: "'Inter Variable', system-ui, sans-serif" }}
        text-rendering="geometricPrecision"
        shape-rendering="geometricPrecision"
      >
        <defs>
          <filter
            id="active-glow"
            x="-50%"
            y="-50%"
            width="200%"
            height="200%"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation="5" result="blur" />
            <feFlood floodColor={COLORS.glow} floodOpacity="0.4" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="shadow" />
            <feMerge>
              <feMergeNode in="shadow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter
            id="active-glow-strong"
            x="-60%"
            y="-60%"
            width="220%"
            height="220%"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
            <feFlood floodColor={COLORS.glow} floodOpacity="0.55" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="shadow" />
            <feMerge>
              <feMergeNode in="shadow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter
            id="node-shadow"
            x="-15%"
            y="-15%"
            width="130%"
            height="140%"
          >
            <feDropShadow dx="0" dy="2" stdDeviation="4" floodColor={COLORS.shadow} />
          </filter>
          <linearGradient id="edge-active" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={COLORS.edgeActive.from} stopOpacity="0.85" />
            <stop offset="100%" stopColor={COLORS.edgeActive.to} stopOpacity="0.5" />
          </linearGradient>
          <linearGradient
            id="edge-completed"
            x1="0%"
            y1="0%"
            x2="100%"
            y2="0%"
          >
            <stop offset="0%" stopColor={COLORS.edgeCompleted.from} stopOpacity="0.6" />
            <stop offset="100%" stopColor={COLORS.edgeCompleted.to} stopOpacity="0.25" />
          </linearGradient>
        </defs>

        {/* ── Edges ──────────────────────────────────────────────────── */}
        {EDGES.map(([from, to]) => {
          const [fc, fr] = POS[from];
          const [tc, tr] = POS[to];
          const fromState = state.nodes[from] ?? "pending";
          const toState = state.nodes[to] ?? "pending";
          const isActive = fromState === "completed" && toState === "active";
          const isCompleted = toState === "completed";
          const isPending = !isActive && !isCompleted;

          return (
            <g key={`${from}-${to}`}>
              <path
                d={edgePath(fc, fr, tc, tr)}
                fill="none"
                strokeWidth={2.5}
                className={
                  isPending
                    ? "stroke-ink-300/50 dark:stroke-ink-700/50"
                    : ""
                }
                stroke={
                  isActive
                    ? "url(#edge-active)"
                    : isCompleted
                      ? "url(#edge-completed)"
                      : undefined
                }
              />
              {isActive && (
                <path
                  d={edgePath(fc, fr, tc, tr)}
                  fill="none"
                  stroke={COLORS.node.active.stroke}
                  strokeWidth={3}
                  strokeDasharray="8 6"
                  className="animate-edge-march"
                  opacity={0.75}
                />
              )}
            </g>
          );
        })}

        {/* Loopback edge (judge → review, only when judge requested revision) */}
        {state.judgeRevising && (
          <g>
            <path
              d={loopbackPath()}
              fill="none"
              stroke={COLORS.loopback}
              strokeWidth={2.5}
              strokeDasharray="6 4"
              className="animate-edge-march"
              markerEnd="url(#arrowhead-amber)"
            />
            <defs>
              <marker
                id="arrowhead-amber"
                viewBox="0 0 10 7"
                refX="9"
                refY="3.5"
                markerWidth="9"
                markerHeight="7"
                orient="auto"
              >
                <polygon points="0 0, 10 3.5, 0 7" fill={COLORS.loopback} />
              </marker>
            </defs>
          </g>
        )}

        {/* ── Main nodes ─────────────────────────────────────────────── */}
        {MAIN_NODES.map((n) => {
          const nodeState = state.nodes[n.id] ?? "pending";
          const isActive = state.activeNodes.has(n.id);
          const isCompleted = nodeState === "completed";
          const isError = nodeState === "error";
          const isHovered = hoveredNode === n.id;

          let fill: string;
          let stroke: string;
          let textFill: string;
          let subFill: string;

          if (isError) {
            fill = COLORS.node.error.fill;
            stroke = COLORS.node.error.stroke;
            textFill = COLORS.node.error.text;
            subFill = COLORS.node.error.sub;
          } else if (isActive) {
            fill = COLORS.node.active.fill;
            stroke = COLORS.node.active.stroke;
            textFill = COLORS.node.active.text;
            subFill = COLORS.node.active.sub;
          } else if (isCompleted) {
            fill = COLORS.node.done.fill;
            stroke = COLORS.node.done.stroke;
            textFill = COLORS.node.done.text;
            subFill = COLORS.node.done.sub;
          } else {
            fill = COLORS.node.pending.fill;
            stroke = COLORS.node.pending.stroke;
            textFill = COLORS.node.pending.text;
            subFill = COLORS.node.pending.sub;
          }

          const nodeFilter = isError
            ? undefined
            : isActive
              ? "url(#active-glow-strong)"
              : "url(#node-shadow)";

          return (
            <g
              key={n.id}
              filter={nodeFilter}
              onMouseEnter={() => setHoveredNode(n.id)}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() =>
                nodeState !== "pending" ? onNodeClick?.(n.id) : null
              }
              style={{
                cursor: nodeState !== "pending" ? "pointer" : "default",
              }}
            >
              {/* Outer glow ring for active nodes — SVG-native pulse (no CSS transform on SVG) */}
              {isActive && (
                <rect
                  x={x0(n.col) - 6}
                  y={y0(n.row) - 6}
                  width={NODE_W + 12}
                  height={NODE_H + 12}
                  rx={16}
                  fill="none"
                  stroke={COLORS.node.active.stroke}
                  strokeWidth={2}
                  opacity={0.35}
                >
                  <animate attributeName="opacity" values="0.35;0.1;0.35" dur="2.5s" repeatCount="indefinite" />
                </rect>
              )}

              <rect
                x={x0(n.col)}
                y={y0(n.row)}
                width={NODE_W}
                height={NODE_H}
                rx={14}
                fill={fill}
                stroke={stroke}
                strokeWidth={
                  isActive ? 3 : isHovered && !isActive ? 2.5 : 1.5
                }
                className={`transition-all duration-700 ${
                  isCompleted
                    ? "animate-node-complete-pop"
                    : isError
                      ? "animate-node-error-shake"
                      : ""
                }`}
                style={{
                  transformOrigin: `${cx(n.col)}px ${cy(n.row)}px`,
                }}
              />
              {/* Left accent bar */}
              <rect
                x={x0(n.col)}
                y={y0(n.row) + 8}
                width={5}
                height={NODE_H - 16}
                rx={2.5}
                fill={subFill}
                className="transition-colors duration-700"
              />
              {/* Icon */}
              <g
                transform={`translate(${x0(n.col) + 34}, ${y0(n.row) + NODE_H / 2})`}
              >
                <path
                  d={NODE_ICONS[n.id] ?? ""}
                  fill={subFill}
                  transform="translate(-9,-9) scale(0.75,0.75)"
                />
              </g>
              {/* Label */}
              <text
                x={x0(n.col) + 60}
                y={y0(n.row) + NODE_H / 2 + 1}
                fill={textFill}
                fontSize={15}
                fontWeight={600}
                dominantBaseline="middle"
                className="transition-colors duration-700"
              >
                {n.label}
              </text>
              {/* Active indicator: static dot with SVG-native opacity pulse */}
              {isActive && (
                <circle cx={x0(n.col) + NODE_W - 20} cy={y0(n.row) + 18} r={6} fill={COLORS.node.active.stroke}>
                  <animate attributeName="opacity" values="1;0.4;1" dur="1.8s" repeatCount="indefinite" />
                </circle>
              )}
              {/* Checkmark */}
              {isCompleted && (
                <g
                  transform={`translate(${x0(n.col) + NODE_W - 26}, ${y0(n.row) + 18})`}
                >
                  <circle r={11} fill={COLORS.node.done.sub} />
                  <path
                    d="M-4.5 0 L-1.5 3.5 L4.5 -3.5"
                    fill="none"
                    stroke="white"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </g>
              )}
              {/* Error X */}
              {isError && (
                <g
                  transform={`translate(${x0(n.col) + NODE_W - 26}, ${y0(n.row) + 18})`}
                >
                  <circle r={11} fill={COLORS.node.error.stroke} />
                  <path
                    d="M-4 -4 L4 4 M-4 4 L4 -4"
                    fill="none"
                    stroke="white"
                    strokeWidth={2}
                    strokeLinecap="round"
                  />
                </g>
              )}
            </g>
          );
        })}

        {/* ── Hover tooltip (foreignObject overlay) ───────────────────── */}
        {hoveredNode &&
          nodeDetail &&
          (() => {
            const n = MAIN_NODES.find((m) => m.id === hoveredNode);
            if (!n) return null;
            const placeRight = n.col <= 3;
            const tipW = 280;
            // Dynamic height based on content
            let lineCount = nodeDetail.lines.length;
            if (nodeDetail.researchSources?.length) lineCount += 2;
            if (nodeDetail.analyzeDocuments?.length) lineCount += 1;
            if (nodeDetail.chapterDetails?.length) lineCount += 1;
            if (nodeDetail.errorDetail) lineCount += 2;
            const tipH = Math.min(70 + lineCount * 20, 400);
            const gap = 16;
            const fx = placeRight
              ? x0(n.col) + NODE_W + gap
              : x0(n.col) - tipW - gap;
            const fy = y0(n.row) - 10;
            const badge = statusBadge(nodeDetail.status);
            const hasRichContent =
              nodeDetail.researchSources ||
              nodeDetail.analyzeDocuments ||
              nodeDetail.chapterDetails ||
              nodeDetail.errorDetail;

            return (
              <foreignObject
                x={fx}
                y={fy}
                width={tipW}
                height={tipH}
                style={{ overflow: "visible" }}
              >
                <div
                  className="animate-tooltip-fade-in rounded-xl border border-ink-200/80 bg-white/98 p-3.5 text-xs shadow-xl backdrop-blur-sm dark:border-ink-700 dark:bg-ink-900/98"
                  style={{ width: tipW, fontFamily: "'Inter Variable', system-ui, sans-serif" }}
                >
                  {/* Header */}
                  <div className="mb-2.5 flex items-center gap-2">
                    <svg
                      width={15}
                      height={15}
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke={badge.color}
                      strokeWidth={2}
                      className="shrink-0"
                    >
                      <path d={NODE_ICONS[hoveredNode] ?? ""} />
                    </svg>
                    <span className="font-semibold text-ink-900 dark:text-ink-100 text-sm">
                      {nodeDetail.title}
                    </span>
                    <span
                      className="ml-auto shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold"
                      style={{
                        backgroundColor: badge.color + "18",
                        color: badge.color,
                      }}
                    >
                      {badge.label}
                    </span>
                  </div>

                  {/* Divider */}
                  <div className="mb-2.5 h-px w-full bg-ink-200/50 dark:bg-ink-700/50" />

                  {/* Research sources rich display */}
                  {nodeDetail.researchSources && nodeDetail.researchSources.length > 0 && (
                    <div className="mb-2 space-y-1">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500">
                        Sources ({nodeDetail.researchSources.length})
                      </div>
                      <div className="max-h-[140px] space-y-1 overflow-y-auto">
                        {nodeDetail.researchSources.slice(0, 5).map((src, i) => {
                          const sourceColor =
                            src.source?.toLowerCase().includes("arxiv")
                              ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300"
                              : src.source?.toLowerCase().includes("wikipedia")
                                ? "bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300"
                                : src.source?.toLowerCase().includes("tavily")
                                  ? "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300"
                                  : "bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300";
                          return (
                            <div
                              key={i}
                              className="flex items-start gap-1.5 rounded-md bg-ink-50/50 px-2 py-1.5 dark:bg-ink-800/50"
                            >
                              <span className={`mt-0.5 shrink-0 rounded px-1 py-[1px] text-[9px] font-semibold uppercase ${sourceColor}`}>
                                {src.source?.slice(0, 6) ?? "web"}
                              </span>
                              <span className="leading-tight text-ink-700 dark:text-ink-300">
                                {ellipsis(src.title, 60)}
                              </span>
                            </div>
                          );
                        })}
                        {nodeDetail.researchSources.length > 5 && (
                          <div className="text-[11px] text-ink-400 dark:text-ink-500">
                            … +{nodeDetail.researchSources.length - 5} more
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Analyze documents rich display */}
                  {nodeDetail.analyzeDocuments && nodeDetail.analyzeDocuments.length > 0 && (
                    <div className="mb-2 space-y-1">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500">
                        Documents ({nodeDetail.analyzeDocuments.length})
                      </div>
                      <div className="max-h-[100px] space-y-0.5 overflow-y-auto">
                        {nodeDetail.analyzeDocuments.slice(0, 4).map((doc, i) => (
                          <div key={i} className="flex items-center gap-1.5 px-2 py-1 text-ink-700 dark:text-ink-300">
                            <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="shrink-0 text-ink-400">
                              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                              <polyline points="14 2 14 8 20 8" />
                            </svg>
                            <span>{ellipsis(doc, 50)}</span>
                          </div>
                        ))}
                        {nodeDetail.analyzeDocuments.length > 4 && (
                          <div className="px-2 text-[11px] text-ink-400">
                            … +{nodeDetail.analyzeDocuments.length - 4} more
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Chapter details rich display */}
                  {nodeDetail.chapterDetails && nodeDetail.chapterDetails.length > 0 && (
                    <div className="mb-2 space-y-1">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500">
                        Chapters ({nodeDetail.chapterDetails.length})
                      </div>
                      <div className="max-h-[120px] space-y-1 overflow-y-auto">
                        {nodeDetail.chapterDetails.map((ch, i) => {
                          const pct = ch.total > 0 ? Math.round((ch.done / ch.total) * 100) : 0;
                          return (
                            <div key={i} className="px-2 py-1">
                              <div className="mb-0.5 flex items-center justify-between text-[11px] text-ink-700 dark:text-ink-300">
                                <span className="truncate">{ellipsis(ch.name, 22)}</span>
                                <span className="ml-2 shrink-0 tabular-nums text-ink-400">
                                  {ch.done}/{ch.total}
                                </span>
                              </div>
                              <div className="h-1 w-full overflow-hidden rounded-full bg-ink-200 dark:bg-ink-700">
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

                  {/* Error detail rich display */}
                  {nodeDetail.errorDetail && (
                    <div className="mb-2 space-y-1">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-red-500 dark:text-red-400">
                        LaTeX Error
                      </div>
                      <div className="max-h-[100px] overflow-y-auto rounded-lg bg-red-50/80 p-2 font-mono text-[10px] leading-relaxed text-red-800 dark:bg-red-950/60 dark:text-red-200">
                        {nodeDetail.errorDetail.split("\n").slice(0, 4).map((line, i) => (
                          <div key={i}>{line || "\u00A0"}</div>
                        ))}
                        {nodeDetail.errorDetail.split("\n").length > 4 && (
                          <div className="mt-1 text-red-400 dark:text-red-500">
                            … +{nodeDetail.errorDetail.split("\n").length - 4} lines
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Default line-based content */}
                  {!hasRichContent && (
                    <div className="space-y-1">
                      {nodeDetail.lines.map((line, i) => {
                        const isSection = line.startsWith("  ");
                        return (
                          <div
                            key={i}
                            className={`leading-relaxed ${
                              isSection
                                ? "ml-2 text-ink-500 dark:text-ink-400"
                                : "text-ink-700 dark:text-ink-300"
                            }`}
                          >
                            {line.trimStart()}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Compact line list when rich content present but lines also exist */}
                  {hasRichContent && nodeDetail.lines.length > 0 && (
                    <div className="mt-2 space-y-0.5 border-t border-ink-200/50 pt-2 dark:border-ink-700/50">
                      {nodeDetail.lines.map((line, i) => {
                        const isSection = line.startsWith("  ");
                        return (
                          <div
                            key={i}
                            className={`text-[11px] leading-relaxed ${
                              isSection
                                ? "ml-2 text-ink-500 dark:text-ink-400"
                                : "text-ink-700 dark:text-ink-300"
                            }`}
                          >
                            {line.trimStart()}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </foreignObject>
            );
          })()}

        {/* ── Chapter sub-nodes (during writing) ──────────────────────── */}
        {chapterCount > 0 && (
          <g>
            {state.chapters.map((ch, i) => {
              const cxChap = chapterX(i, chapterCount) + CHAPTER_W / 2;
              const cyChap = CHAPTER_START_Y;
              const writeBottom = cy(0) + NODE_H / 2;
              return (
                <line
                  key={`cl-${i}`}
                  x1={cx(4)}
                  y1={writeBottom}
                  x2={cxChap}
                  y2={cyChap}
                  stroke={
                    state.chapterProgress[ch.name]?.done ===
                      state.chapterProgress[ch.name]?.total &&
                    state.chapterProgress[ch.name]?.total > 0
                      ? COLORS.chapter.connectorDone
                      : COLORS.chapter.connectorPending
                  }
                  strokeWidth={1.5}
                  className="transition-colors duration-500"
                />
              );
            })}

            {state.chapters.map((ch, i) => {
              const progress = state.chapterProgress[ch.name];
              const done = progress?.done ?? 0;
              const total = progress?.total ?? ch.sections;
              const ratio = total > 0 ? done / total : 0;
              const isActive = done > 0 && done < total;
              const isDone = done === total && total > 0;

              let chapFill: string;
              let chapStroke: string;
              let chapText: string;

              if (isDone) {
                chapFill = COLORS.chapter.done.fill;
                chapStroke = COLORS.chapter.done.stroke;
                chapText = COLORS.chapter.done.text;
              } else if (isActive) {
                chapFill = COLORS.chapter.active.fill;
                chapStroke = COLORS.chapter.active.stroke;
                chapText = COLORS.chapter.active.text;
              } else {
                chapFill = COLORS.chapter.pending.fill;
                chapStroke = COLORS.chapter.pending.stroke;
                chapText = COLORS.chapter.pending.text;
              }

              return (
                <g key={`ch-${i}`}>
                  <rect
                    x={chapterX(i, chapterCount)}
                    y={CHAPTER_START_Y}
                    width={CHAPTER_W}
                    height={CHAPTER_H}
                    rx={10}
                    fill={chapFill}
                    stroke={chapStroke}
                    strokeWidth={isActive ? 2.5 : 1.5}
                    className={`transition-all duration-700 ${
                      isDone
                        ? "animate-node-complete-pop"
                        : ""
                    }`}
                    style={{
                      transformOrigin: `${chapterX(i, chapterCount) + CHAPTER_W / 2}px ${CHAPTER_START_Y + CHAPTER_H / 2}px`,
                    }}
                    filter={isActive ? "url(#active-glow)" : undefined}
                  />
                  {/* Progress bar background */}
                  <rect
                    x={chapterX(i, chapterCount) + 5}
                    y={CHAPTER_START_Y + CHAPTER_H - 11}
                    width={CHAPTER_W - 10}
                    height={5}
                    rx={2.5}
                    fill={COLORS.chapter.progressBg}
                  />
                  {/* Progress bar fill */}
                  <rect
                    x={chapterX(i, chapterCount) + 5}
                    y={CHAPTER_START_Y + CHAPTER_H - 11}
                    width={(CHAPTER_W - 10) * ratio}
                    height={5}
                    rx={2.5}
                    fill={isDone ? COLORS.chapter.done.stroke : COLORS.chapter.active.stroke}
                    className="transition-all duration-700"
                  />
                  {/* Chapter name */}
                  <text
                    x={chapterX(i, chapterCount) + CHAPTER_W / 2}
                    y={CHAPTER_START_Y + 19}
                    textAnchor="middle"
                    fill={chapText}
                    fontSize={13}
                    fontWeight={600}
                    className="transition-colors duration-500"
                  >
                    {ch.name.length > 18
                      ? ch.name.slice(0, 17) + "…"
                      : ch.name}
                  </text>
                  {/* Section count */}
                  <text
                    x={chapterX(i, chapterCount) + CHAPTER_W / 2}
                    y={CHAPTER_START_Y + 35}
                    textAnchor="middle"
                    fill={
                      isDone
                        ? COLORS.chapter.done.stroke
                        : isActive
                          ? COLORS.chapter.active.stroke
                          : COLORS.node.pending.sub
                    }
                    fontSize={11}
                    className="transition-colors duration-500"
                  >
                    {done}/{total} sections
                  </text>
                  {/* Done badge */}
                  {isDone && (
                    <g
                      transform={`translate(${chapterX(i, chapterCount) + CHAPTER_W - 14}, ${CHAPTER_START_Y + 11})`}
                    >
                      <circle r={8} fill={COLORS.node.done.sub} />
                      <path
                        d="M-3.5 0 L-1.5 2.5 L3.5 -2.5"
                        fill="none"
                        stroke="white"
                        strokeWidth={1.8}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </g>
                  )}
                </g>
              );
            })}
          </g>
        )}
      </svg>
    </div>
  );
}
