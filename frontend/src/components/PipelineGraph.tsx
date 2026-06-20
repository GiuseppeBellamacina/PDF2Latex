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
  chapterX,
  cx,
  cy,
  deriveNodeDetails,
  deriveState,
  edgePath,
  loopbackPath,
  statusBadge,
  x0,
  y0,
} from "./PipelineGraph.utils";

/* ── Component ──────────────────────────────────────────────────────────── */

interface Props {
  events: ProgressEvent[];
  onNodeClick?: (nodeId: string) => void;
}

export default function PipelineGraph({ events, onNodeClick }: Props) {
  const state = useMemo(() => deriveState(events), [events]);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const nodeDetail = hoveredNode
    ? deriveNodeDetails(hoveredNode, events, state)
    : null;

  // svg dimensions: accommodate the rightmost node (judge, col 8).
  const svgW = cx(8) + NODE_W / 2 + 30;
  const chapterCount = state.chapters.length;
  const chaptersHeight =
    chapterCount > 0
      ? CHAPTER_START_Y + chapterCount * CHAPTER_ROW_H + 20 - CENTER_Y
      : 0;
  const svgH = Math.max(
    CENTER_Y + NODE_H / 2 + 60,
    CENTER_Y + chaptersHeight + 40,
  );

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-200/60 bg-gradient-to-br from-ink-50 via-white to-ink-50 p-4 dark:border-ink-800/60 dark:from-ink-950 dark:via-ink-900 dark:to-ink-950">
      <svg
        viewBox={`0 0 ${svgW} ${svgH}`}
        className="w-full min-w-[1000px]"
        style={{ fontFamily: "system-ui, sans-serif" }}
      >
        <defs>
          <filter
            id="active-glow"
            x="-40%"
            y="-40%"
            width="180%"
            height="180%"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur" />
            <feFlood floodColor={COLORS.glow} floodOpacity="0.35" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="shadow" />
            <feMerge>
              <feMergeNode in="shadow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter
            id="node-shadow"
            x="-10%"
            y="-10%"
            width="120%"
            height="130%"
          >
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor={COLORS.shadow} />
          </filter>
          <linearGradient id="edge-active" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={COLORS.edgeActive.from} stopOpacity="0.8" />
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
            <stop offset="100%" stopColor={COLORS.edgeCompleted.to} stopOpacity="0.3" />
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
                strokeWidth={2}
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
                  strokeWidth={2.5}
                  strokeDasharray="8 6"
                  className="animate-edge-march"
                  opacity={0.7}
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
              strokeWidth={2}
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
                markerWidth="8"
                markerHeight="6"
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

          return (
            <g
              key={n.id}
              filter={isActive ? "url(#active-glow)" : "url(#node-shadow)"}
              onMouseEnter={() => setHoveredNode(n.id)}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() =>
                nodeState !== "pending" ? onNodeClick?.(n.id) : null
              }
              style={{
                cursor: nodeState !== "pending" ? "pointer" : "default",
              }}
            >
              <rect
                x={x0(n.col)}
                y={y0(n.row)}
                width={NODE_W}
                height={NODE_H}
                rx={12}
                fill={fill}
                stroke={stroke}
                strokeWidth={
                  isActive ? 2.5 : isHovered && !isActive ? 2 : 1.5
                }
                className={`transition-all duration-700 ${
                  isActive
                    ? "animate-node-active-glow"
                    : isCompleted
                      ? "animate-node-complete-pop"
                      : isError
                        ? "animate-node-error-shake"
                        : ""
                }`}
                style={{
                  transformOrigin: `${cx(n.col)}px ${cy(n.row)}px`,
                }}
              />
              <rect
                x={x0(n.col)}
                y={y0(n.row) + 6}
                width={4}
                height={NODE_H - 12}
                rx={2}
                fill={subFill}
                className="transition-colors duration-700"
              />
              <g
                transform={`translate(${x0(n.col) + 32}, ${y0(n.row) + NODE_H / 2})`}
              >
                <path
                  d={NODE_ICONS[n.id] ?? ""}
                  fill={subFill}
                  transform="translate(-8,-8) scale(0.7,0.7)"
                />
              </g>
              <text
                x={x0(n.col) + 56}
                y={y0(n.row) + NODE_H / 2 + 1}
                fill={textFill}
                fontSize={14}
                fontWeight={600}
                dominantBaseline="middle"
                className="transition-colors duration-700"
              >
                {n.label}
              </text>
              {isActive && (
                <>
                  <circle cx={x0(n.col) + NODE_W - 18} cy={y0(n.row) + 16} r={5} fill={COLORS.node.active.stroke} className="animate-pulse-dot" />
                  <circle cx={x0(n.col) + NODE_W - 18} cy={y0(n.row) + 16} r={5} fill={COLORS.node.active.stroke} opacity={0.3} className="animate-pulse-ring" />
                </>
              )}
              {isCompleted && (
                <g
                  transform={`translate(${x0(n.col) + NODE_W - 24}, ${y0(n.row) + 16})`}
                >
                  <circle r={10} fill={COLORS.node.done.sub} />
                  <path
                    d="M-4 0 L-1.5 3 L4 -3"
                    fill="none"
                    stroke="white"
                    strokeWidth={1.8}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </g>
              )}
              {isError && (
                <g
                  transform={`translate(${x0(n.col) + NODE_W - 24}, ${y0(n.row) + 16})`}
                >
                  <circle r={10} fill={COLORS.node.error.stroke} />
                  <path
                    d="M-3 -3 L3 3 M-3 3 L3 -3"
                    fill="none"
                    stroke="white"
                    strokeWidth={1.8}
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
            const placeRight = n.col <= 2;
            const tipW = 260;
            const tipH = Math.min(60 + nodeDetail.lines.length * 20, 320);
            const gap = 14;
            const fx = placeRight
              ? x0(n.col) + NODE_W + gap
              : x0(n.col) - tipW - gap;
            const fy = y0(n.row) - 8;
            const badge = statusBadge(nodeDetail.status);
            const levelColor =
              nodeDetail.level === "error"
                ? COLORS.level.error
                : nodeDetail.level === "warning"
                  ? COLORS.level.warning
                  : nodeDetail.level === "success"
                    ? COLORS.level.success
                    : COLORS.level.info;

            return (
              <foreignObject
                x={fx}
                y={fy}
                width={tipW}
                height={tipH}
                style={{ overflow: "visible" }}
              >
                <div
                  className="rounded-xl border border-ink-200 bg-white/95 p-3 text-xs shadow-xl backdrop-blur-sm dark:border-ink-700 dark:bg-ink-900/95"
                  style={{ width: tipW, fontFamily: "system-ui, sans-serif" }}
                >
                  <div className="mb-2 flex items-center gap-2">
                    <svg
                      width={14}
                      height={14}
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke={badge.color}
                      strokeWidth={2}
                    >
                      <path d={NODE_ICONS[hoveredNode] ?? ""} />
                    </svg>
                    <span className="font-semibold text-ink-900 dark:text-ink-100">
                      {nodeDetail.title}
                    </span>
                    <span
                      className="ml-auto rounded-full px-2 py-0.5 text-[10px] font-medium"
                      style={{
                        backgroundColor: badge.color + "18",
                        color: badge.color,
                      }}
                    >
                      {badge.label}
                    </span>
                  </div>
                  <div
                    className="mb-2 h-0.5 w-full rounded-full"
                    style={{ backgroundColor: levelColor + "30" }}
                  />
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
                    rx={8}
                    fill={chapFill}
                    stroke={chapStroke}
                    strokeWidth={isActive ? 2 : 1}
                    className={`transition-all duration-700 ${
                      isActive
                        ? "animate-node-active-glow"
                        : isDone
                          ? "animate-node-complete-pop"
                          : ""
                    }`}
                    style={{
                      transformOrigin: `${chapterX(i, chapterCount) + CHAPTER_W / 2}px ${CHAPTER_START_Y + CHAPTER_H / 2}px`,
                    }}
                    filter={isActive ? "url(#active-glow)" : undefined}
                  />
                  <rect
                    x={chapterX(i, chapterCount) + 4}
                    y={CHAPTER_START_Y + CHAPTER_H - 10}
                    width={CHAPTER_W - 8}
                    height={4}
                    rx={2}
                    fill={COLORS.chapter.progressBg}
                    className="dark:fill-ink-800"
                  />
                  {ratio > 0 && (
                    <rect
                      x={chapterX(i, chapterCount) + 4}
                      y={CHAPTER_START_Y + CHAPTER_H - 10}
                      width={(CHAPTER_W - 8) * ratio}
                      height={4}
                      rx={2}
                      fill={isDone ? COLORS.chapter.done.stroke : COLORS.chapter.active.stroke}
                      className="transition-all duration-700"
                    />
                  )}
                  <text
                    x={chapterX(i, chapterCount) + CHAPTER_W / 2}
                    y={CHAPTER_START_Y + 18}
                    textAnchor="middle"
                    fill={chapText}
                    fontSize={12}
                    fontWeight={600}
                    className="transition-colors duration-500"
                  >
                    {ch.name.length > 16
                      ? ch.name.slice(0, 15) + "…"
                      : ch.name}
                  </text>
                  <text
                    x={chapterX(i, chapterCount) + CHAPTER_W / 2}
                    y={CHAPTER_START_Y + 33}
                    textAnchor="middle"
                    fill={
                      isDone ? COLORS.chapter.done.stroke : isActive ? COLORS.chapter.active.stroke : COLORS.node.pending.sub
                    }
                    fontSize={10}
                    className="transition-colors duration-500"
                  >
                    {done}/{total} sections
                  </text>
                  {isDone && (
                    <g
                      transform={`translate(${chapterX(i, chapterCount) + CHAPTER_W - 12}, ${CHAPTER_START_Y + 10})`}
                    >
                      <circle r={7} fill={COLORS.node.done.sub} />
                      <path
                        d="M-3 0 L-1 2 L3 -2"
                        fill="none"
                        stroke="white"
                        strokeWidth={1.5}
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
