import { useMemo, useState } from "react";
import type { ProgressEvent } from "../hooks/useGenerateWs";

/* ── Layout constants ──────────────────────────────────────────────────── */
const NODE_W = 148;
const NODE_H = 52;
const CHAPTER_W = 130;
const CHAPTER_H = 36;
const COL_GAP = 80;
const START_X = 24;
const CENTER_Y = 160;
const ROW_SPREAD = 94;

interface GraphNode {
  id: string;
  label: string;
  col: number;
  row: number;
}

const MAIN_NODES: GraphNode[] = [
  { id: "extract", label: "Extract", col: 0, row: 0 },
  { id: "research", label: "Research", col: 1, row: -1 },
  { id: "analyze", label: "Analyze", col: 1, row: 0 },
  { id: "merge_analyses", label: "Merge", col: 2, row: 0 },
  { id: "plan", label: "Plan", col: 3, row: 0 },
  { id: "write", label: "Write", col: 4, row: 0 },
  { id: "overview", label: "Overview", col: 5, row: -1 },
  { id: "coherence", label: "Coherence", col: 5, row: 0 },
  { id: "citations", label: "Citations", col: 5, row: 1 },
  { id: "merge", label: "Merge", col: 6, row: 0 },
  { id: "review", label: "Review", col: 7, row: 0 },
  { id: "judge", label: "Judge", col: 8, row: 0 },
];

/* Map node id → (col, row) */
const POS: Record<string, [number, number]> = {};
for (const n of MAIN_NODES) POS[n.id] = [n.col, n.row];

/* ── Edge definitions: [from, to] ───────────────────────────────────────── */
const EDGES: [string, string][] = [
  /* PDF path */
  ["extract", "analyze"],
  /* Web research path */
  ["research", "merge_analyses"],
  /* Both converge */
  ["analyze", "merge_analyses"],
  ["merge_analyses", "plan"],
  ["plan", "write"],
  ["write", "overview"],
  ["write", "coherence"],
  ["write", "citations"],
  ["overview", "merge"],
  ["coherence", "merge"],
  ["citations", "merge"],
  ["merge", "review"],
  ["review", "judge"],
];

/* ── Helpers ────────────────────────────────────────────────────────────── */

/** Absolute center-x of a node column. */
function cx(col: number): number {
  return START_X + col * (NODE_W + COL_GAP) + NODE_W / 2;
}

/** Absolute center-y of a node row (row 0 = CENTER_Y). */
function cy(row: number): number {
  return CENTER_Y + row * ROW_SPREAD;
}

/** Node top-left corner. */
function x0(col: number): number {
  return cx(col) - NODE_W / 2;
}
function y0(row: number): number {
  return cy(row) - NODE_H / 2;
}

/** Chapter sub-node positions: fan out below the write node. */
const CHAPTER_START_Y = CENTER_Y + NODE_H / 2 + 28;
const CHAPTER_ROW_H = CHAPTER_H + 10;

function chapterX(index: number, total: number): number {
  const totalW = total * CHAPTER_W + (total - 1) * 10;
  const startX = cx(4) - totalW / 2;
  return startX + index * (CHAPTER_W + 10);
}

/** Compute a cubic bezier path string between two node centers. */
function edgePath(
  fromCol: number,
  fromRow: number,
  toCol: number,
  toRow: number,
): string {
  const x1 = cx(fromCol);
  const y1 = cy(fromRow);
  const x2 = cx(toCol);
  const y2 = cy(toRow);
  const dx = Math.abs(x2 - x1) * 0.45;
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

/** Loopback edge from Judge back to Review (arc above). */
function loopbackPath(): string {
  const jx = cx(8);
  const jy = cy(0) - NODE_H / 2;
  const rx = cx(7);
  const ry = cy(0) - NODE_H / 2;
  const midY = jy - 50;
  return `M ${jx} ${jy} C ${jx} ${midY}, ${rx} ${midY}, ${rx} ${ry}`;
}

/* ── State derivation from events ───────────────────────────────────────── */

type NodeState = "pending" | "active" | "completed" | "error";

interface GraphState {
  nodes: Record<string, NodeState>;
  chapters: ChapterInfo[];
  chapterProgress: Record<string, { done: number; total: number }>;
  errorNode: string | null;
  activeNodes: Set<string>;
  judgeRevising: boolean;
}

interface ChapterInfo {
  name: string;
  sections: number;
}

export function deriveState(events: ProgressEvent[]): GraphState {
  const nodes: Record<string, NodeState> = {};
  for (const n of MAIN_NODES) nodes[n.id] = "pending";

  const chapters: ChapterInfo[] = [];
  const chapterProgress: Record<string, { done: number; total: number }> = {};
  const activeNodes = new Set<string>();
  let errorNode: string | null = null;
  let judgeRevising = false;

  const order = [
    "extract", "research", "analyze", "merge_analyses", "plan", "write",
    "overview", "coherence", "citations", "merge", "review", "judge",
  ];
  let highestCompleted = -1;

  for (const e of events) {
    const nid = e.node;
    if (nid && nodes[nid] !== undefined) {
      const idx = order.indexOf(nid);

      if (e.level === "error") {
        nodes[nid] = "error";
        errorNode = nid;
      } else if (e.level === "success") {
        nodes[nid] = "completed";
        if (idx > highestCompleted) highestCompleted = idx;
      }
    }

    // Mark extract as completed when analyze events start arriving.
    if (e.node === "analyze" && nodes["extract"] === "pending") {
      nodes["extract"] = "completed";
    }

    // Mark research as completed when merge_analyses events arrive.
    if (e.node === "merge_analyses" && nodes["research"] === "pending") {
      nodes["research"] = "completed";
    }

    // Chapters planned
    if (e.action === "chapters_planned" && e.chapters) {
      chapters.push(...e.chapters);
      for (const ch of e.chapters) {
        chapterProgress[ch.name] = { done: 0, total: ch.sections };
      }
    }

    // Chapter progress
    if (e.chapter && e.chapter_done !== undefined && e.chapter_total !== undefined) {
      chapterProgress[e.chapter] = { done: e.chapter_done, total: e.chapter_total };
    }

    // Track judge revision action
    if (e.node === "judge" && e.stage === "judging" && e.detail && e.detail.includes("Revisione")) {
      judgeRevising = true;
    }
  }

  // Determine active nodes: all pending nodes whose predecessors are completed.
  for (const nid of order) {
    if (nodes[nid] !== "pending") continue;
    const idx = order.indexOf(nid);
    const allBeforeDone = order.slice(0, idx).every((prev) => nodes[prev] === "completed");
    if (allBeforeDone) {
      activeNodes.add(nid);
    }
  }

  // Mark write as completed when all chapter sections are done.
  if (chapters.length > 0) {
    const allDone = chapters.every(
      (ch) => chapterProgress[ch.name]?.done === chapterProgress[ch.name]?.total && chapterProgress[ch.name]?.total > 0
    );
    if (allDone && nodes["write"] === "pending") {
      nodes["write"] = "completed";
      activeNodes.delete("write");
    }
  }

  // Mark diamond nodes completed if merge is completed.
  if (nodes["merge"] === "completed") {
    for (const n of ["overview", "coherence", "citations"]) {
      if (nodes[n] === "pending") nodes[n] = "completed";
      activeNodes.delete(n);
    }
  }

  // If any node errored, clear activeNodes after it.
  if (errorNode) {
    const errIdx = order.indexOf(errorNode);
    for (const nid of activeNodes) {
      if (order.indexOf(nid) > errIdx) activeNodes.delete(nid);
    }
  }

  return { nodes, chapters, chapterProgress, errorNode, activeNodes, judgeRevising };
}

/* ── Node detail derivation from events ────────────────────────────────── */

export interface NodeDetail {
  title: string;
  status: string;
  lines: string[];
  level?: "info" | "success" | "warning" | "error";
}

export function deriveNodeDetails(
  nodeId: string,
  events: ProgressEvent[],
  state: GraphState,
): NodeDetail | null {
  const status = state.nodes[nodeId] ?? "pending";
  const labels: Record<string, string> = {
    extract: "Extraction",
    research: "Web Research",
    analyze: "Analysis",
    merge_analyses: "Source Merge",
    plan: "Planning",
    write: "Writing",
    overview: "Overview",
    coherence: "Coherence",
    citations: "Citations",
    merge: "Merge",
    review: "Review",
    judge: "Judge",
  };
  const lines: string[] = [];
  let level: "info" | "success" | "warning" | "error" = "info";

  const nodeEvents = events.filter((e) => e.node === nodeId);

  if (nodeId === "extract") {
    const filenames: string[] = [];
    for (const e of nodeEvents) {
      const m = e.message?.match(/^Estrazione (.+) \(\d+\/\d+\)$/);
      if (m) filenames.push(m[1]);
    }
    if (filenames.length) {
      lines.push(`${filenames.length} document${filenames.length !== 1 ? "s" : ""}`);
      for (const f of filenames.slice(0, 5)) lines.push(`  ▸ ${f}`);
      if (filenames.length > 5) lines.push(`  … +${filenames.length - 5} more`);
    }
    const errors = nodeEvents.filter((e) => e.level === "error");
    if (errors.length) { lines.push(`${errors.length} extraction error${errors.length !== 1 ? "s" : ""}`); level = "warning"; }
  } else if (nodeId === "research") {
    const tool = nodeEvents.find((e) => e.detail?.startsWith("tool:"))?.detail;
    if (tool) lines.push(`Using: ${tool.replace("tool: ", "")}`);
    const finish = nodeEvents.find((e) => e.level === "success");
    if (finish?.message) lines.push(finish.message);
    if (finish?.detail) lines.push(finish.detail);
    if (finish?.level === "success") level = "success";
    const warn = nodeEvents.find((e) => e.level === "warning");
    if (warn) { lines.push(warn.message); level = "warning"; }
  } else if (nodeId === "analyze") {
    const finish = nodeEvents.find((e) => e.level === "success");
    if (finish?.detail) lines.push(finish.detail);
    const startDocs = nodeEvents.find((e) => e.documents)?.documents;
    if (startDocs) lines.push(`Processed: ${startDocs.join(", ")}`);
  } else if (nodeId === "merge_analyses") {
    const ev = nodeEvents.find((e) => e.node === "merge_analyses");
    if (ev?.message) lines.push(ev.message);
    if (ev?.detail) lines.push(ev.detail);
    if (ev?.level === "success") level = "success";
  } else if (nodeId === "plan") {
    const finish = nodeEvents.find((e) => e.level === "success" && e.plan);
    if (finish?.plan) {
      lines.push(`${finish.plan.length} section${finish.plan.length !== 1 ? "s" : ""} planned`);
      for (const s of finish.plan.slice(0, 4)) lines.push(`  ▸ ${s.part_title} — ${s.title}`);
      if (finish.plan.length > 4) lines.push(`  … +${finish.plan.length - 4} more`);
    }
  } else if (nodeId === "write") {
    const chapEvent = nodeEvents.find((e) => e.action === "chapters_planned");
    if (chapEvent?.chapters) {
      lines.push(`${chapEvent.chapters.length} chapter${chapEvent.chapters.length !== 1 ? "s" : ""} in parallel`);
      for (const ch of chapEvent.chapters) {
        const prog = state.chapterProgress[ch.name];
        const done = prog?.done ?? 0;
        const total = prog?.total ?? ch.sections;
        const icon = done === total && total > 0 ? "✓" : done > 0 ? "◐" : "○";
        lines.push(`  ${icon} ${ch.name} (${done}/${total})`);
        if (ch.sections > total) lines.push(`    ${ch.sections} sections total`);
      }
    }
    const sectionEvents = nodeEvents.filter((e) => e.chapter_done !== undefined);
    if (sectionEvents.length) lines.push(`${sectionEvents.length} section${sectionEvents.length !== 1 ? "s" : ""} written`);
    const expanding = nodeEvents.find((e) => e.action === "expanding");
    if (expanding) lines.push(`Expanding: ${expanding.detail ?? "…"}`);
  } else if (nodeId === "coherence") {
    const ev = nodeEvents.find((e) => e.detail);
    if (ev?.message) lines.push(ev.message);
    if (ev?.detail) lines.push(ev.detail);
    if (ev?.level === "warning") level = "warning";
    if (ev?.level === "error") level = "error";
  } else if (nodeId === "citations") {
    const ev = nodeEvents.find((e) => e.detail);
    if (ev?.message) lines.push(ev.message);
    if (ev?.detail) lines.push(ev.detail);
    if (ev?.level === "warning") level = "warning";
  } else if (nodeId === "overview") {
    const ev = nodeEvents.find((e) => e.level === "success");
    if (ev?.message) lines.push(ev.message);
    const start = nodeEvents.find((e) => e.progress === 81);
    if (start?.message) lines.push(start.message);
  } else if (nodeId === "merge") {
    const ev = nodeEvents.find((e) => e.node === "merge");
    if (ev?.message) lines.push(ev.message);
    if (ev?.detail) lines.push(ev.detail);
  } else if (nodeId === "review") {
    const successEv = nodeEvents.find((e) => e.level === "success");
    const errorEvs = nodeEvents.filter((e) => e.level === "error" || e.level === "warning");
    if (successEv?.message) { lines.push(successEv.message); level = "success"; }
    if (successEv?.tokens) lines.push(`${successEv.tokens.total_tokens.toLocaleString()} tokens · ${successEv.tokens.calls} LLM calls`);
    for (const err of errorEvs.slice(0, 3)) lines.push(err.detail ?? err.message);
    if (errorEvs.length && !successEv) level = "error";
  } else if (nodeId === "judge") {
    const verdict = nodeEvents.find((e) => e.level === "success");
    const warn = nodeEvents.find((e) => e.level === "warning");
    if (verdict) { lines.push(verdict.message); level = "success"; }
    if (verdict?.detail) lines.push(verdict.detail);
    if (warn) { lines.push(warn.message); level = "warning"; }
    if (warn?.detail) lines.push(warn.detail);
    if (state.judgeRevising) lines.push("↻ Requested structural revision");
  }

  if (lines.length === 0) {
    if (status === "pending") lines.push("Waiting to start…");
    else if (status === "completed") lines.push("Completed");
    else if (status === "active") lines.push("In progress…");
    else if (status === "error") lines.push("Failed");
  }

  return { title: labels[nodeId] ?? nodeId, status, lines, level };
}

/* ── Icons (simple SVG paths) ───────────────────────────────────────────── */

export const NODE_ICONS: Record<string, string> = {
  extract: "M4 4h16v4H4zM4 12h16v2H4zM4 18h12v2H4z",
  research: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z",
  analyze: "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 010-5 2.5 2.5 0 010 5z",
  merge_analyses: "M18 10H6v2h12v-2zm-2 4H8v2h8v-2zm2-8H6v2h12V6zM3 18l4 2v-4l-4 2zm18 0l-4 2v-4l4 2z",
  plan: "M3 5h2V3H3v2zm4 0h10V3H7v2zm-4 6h2V9H3v2zm4 0h10V9H7v2zm-4 6h2v-2H3v2zm4 0h6v-2H7v2z",
  write: "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z",
  overview: "M4 6h16v2H4zm0 5h16v2H4zm0 5h12v2H4z",
  coherence: "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  citations: "M4 4h16v2H4zm0 4h16v2H4zm0 4h12v2H4zM4 4v12l4 4h12V4H4z",
  merge: "M8 3v18l8-9-8-9z",
  review: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 2l5 5h-5V4zM8 13h8v2H8v-2zm0 4h8v2H8v-2zm0-8h3v2H8V9z",
  judge: "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z",
};

/* ── Component ──────────────────────────────────────────────────────────── */

interface Props {
  events: ProgressEvent[];
  onNodeClick?: (nodeId: string) => void;
}

export default function PipelineGraph({ events, onNodeClick }: Props) {
  const state = useMemo(() => deriveState(events), [events]);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const nodeDetail = hoveredNode ? deriveNodeDetails(hoveredNode, events, state) : null;

  // svg dimensions: accommodate the rightmost node (judge, col 8).
  const svgW = cx(8) + NODE_W / 2 + 30;
  const chapterCount = state.chapters.length;
  const chaptersHeight =
    chapterCount > 0
      ? CHAPTER_START_Y + chapterCount * CHAPTER_ROW_H + 20 - CENTER_Y
      : 0;
  const svgH = Math.max(CENTER_Y + NODE_H / 2 + 60, CENTER_Y + chaptersHeight + 40);

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-200/60 bg-gradient-to-br from-ink-50 via-white to-ink-50 p-2 dark:border-ink-800/60 dark:from-ink-950 dark:via-ink-900 dark:to-ink-950">
      <svg
        viewBox={`0 0 ${svgW} ${svgH}`}
        className="w-full min-w-[900px]"
        style={{ fontFamily: "system-ui, sans-serif" }}
      >
        <defs>
          <filter id="active-glow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur" />
            <feFlood floodColor="#10B981" floodOpacity="0.35" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="shadow" />
            <feMerge>
              <feMergeNode in="shadow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="node-shadow" x="-10%" y="-10%" width="120%" height="130%">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#00000022" />
          </filter>
          <linearGradient id="edge-active" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#10B981" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#34D399" stopOpacity="0.5" />
          </linearGradient>
          <linearGradient id="edge-completed" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#059669" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#10B981" stopOpacity="0.3" />
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
                stroke={isActive ? "url(#edge-active)" : isCompleted ? "url(#edge-completed)" : undefined}
              />
              {isActive && (
                <>
                  <path
                    d={edgePath(fc, fr, tc, tr)}
                    fill="none"
                    stroke="#10B981"
                    strokeWidth={2.5}
                    strokeDasharray="8 6"
                    className="animate-edge-march"
                    opacity={0.7}
                  />
                  {[0, 1, 2].map((p) => {
                    const pathD = edgePath(fc, fr, tc, tr);
                    return (
                      <g key={`p-${from}-${to}-${p}`}>
                        <circle
                          r={7}
                          fill="#34D399"
                          opacity={0}
                          className="animate-particle-trail"
                          style={{
                            offsetPath: `path("${pathD}")`,
                            animationDelay: `${p * 0.6}s`,
                          }}
                        />
                        <circle
                          r={3.5}
                          fill="#10B981"
                          opacity={0}
                          className="animate-particle"
                          style={{
                            offsetPath: `path("${pathD}")`,
                            animationDelay: `${p * 0.6}s`,
                          }}
                        />
                      </g>
                    );
                  })}
                  {/* ── Spark burst at destination ──────────────────────── */}
                  <g transform={`translate(${cx(tc)}, ${cy(tr)})`}>
                    {[0, 1, 2].map((burstIdx) => (
                      <g key={`burst-${from}-${to}-${burstIdx}`}>
                        {/* Central flash */}
                        <circle
                          r={2.5}
                          fill="white"
                          opacity={0}
                          className="animate-spark-flash"
                          style={{
                            animationDelay: `${burstIdx * 0.6}s`,
                          }}
                        />
                        {/* Directional sparks */}
                        {[
                          ["0", "#34D399"],
                          ["60", "#6EE7B7"],
                          ["120", "white"],
                          ["180", "#34D399"],
                          ["240", "#A7F3D0"],
                          ["300", "white"],
                        ].map(([angle, color], si) => (
                          <circle
                            key={`spark-${angle}`}
                            r={si === 2 || si === 5 ? 1.3 : 2}
                            fill={color}
                            opacity={0}
                            className={`animate-spark-${angle}`}
                            style={{
                              animationDelay: `${burstIdx * 0.6 + si * 0.04}s`,
                            }}
                          />
                        ))}
                      </g>
                    ))}
                  </g>
                </>
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
              stroke="#F59E0B"
              strokeWidth={2}
              strokeDasharray="6 4"
              className="animate-edge-march"
              markerEnd="url(#arrowhead-amber)"
            />
            <defs>
              <marker id="arrowhead-amber" viewBox="0 0 10 7" refX="9" refY="3.5" markerWidth="8" markerHeight="6" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="#F59E0B" />
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
            fill = "#FEF2F2";
            stroke = "#EF4444";
            textFill = "#991B1B";
            subFill = "#DC2626";
          } else if (isActive) {
            fill = "#ECFDF5";
            stroke = "#10B981";
            textFill = "#065F46";
            subFill = "#059669";
          } else if (isCompleted) {
            fill = "#F0FDF4";
            stroke = "#34D399";
            textFill = "#065F46";
            subFill = "#10B981";
          } else {
            fill = "#F9FAFB";
            stroke = "#D1D5DB";
            textFill = "#6B7280";
            subFill = "#9CA3AF";
          }

          return (
            <g
              key={n.id}
              filter={isActive ? "url(#active-glow)" : "url(#node-shadow)"}
              onMouseEnter={() => setHoveredNode(n.id)}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() => (nodeState !== "pending" ? onNodeClick?.(n.id) : null)}
              style={{ cursor: nodeState !== "pending" ? "pointer" : "default" }}
            >
              <rect
                x={x0(n.col)}
                y={y0(n.row)}
                width={NODE_W}
                height={NODE_H}
                rx={12}
                fill={fill}
                stroke={stroke}
                strokeWidth={isActive ? 2.5 : isHovered && !isActive ? 2 : 1.5}
                className="transition-all duration-500"
              />
              <rect
                x={x0(n.col)}
                y={y0(n.row) + 6}
                width={4}
                height={NODE_H - 12}
                rx={2}
                fill={subFill}
                className="transition-colors duration-500"
              />
              <g transform={`translate(${x0(n.col) + 28}, ${y0(n.row) + NODE_H / 2})`}>
                <path d={NODE_ICONS[n.id] ?? ""} fill={subFill} transform="translate(-8,-8) scale(0.65,0.65)" />
              </g>
              <text
                x={x0(n.col) + 52}
                y={y0(n.row) + NODE_H / 2 + 1}
                fill={textFill}
                fontSize={13}
                fontWeight={600}
                dominantBaseline="middle"
                className="transition-colors duration-500"
              >
                {n.label}
              </text>
              {isActive && (
                <>
                  <circle cx={x0(n.col) + NODE_W - 16} cy={y0(n.row) + 14} r={5} fill="#10B981" className="animate-pulse-dot" />
                  <circle cx={x0(n.col) + NODE_W - 16} cy={y0(n.row) + 14} r={5} fill="#10B981" opacity={0.3} className="animate-pulse-ring" />
                </>
              )}
              {isCompleted && (
                <g transform={`translate(${x0(n.col) + NODE_W - 22}, ${y0(n.row) + 14})`}>
                  <circle r={9} fill="#10B981" />
                  <path d="M-4 0 L-1.5 3 L4 -3" fill="none" stroke="white" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
                </g>
              )}
              {isError && (
                <g transform={`translate(${x0(n.col) + NODE_W - 22}, ${y0(n.row) + 14})`}>
                  <circle r={9} fill="#EF4444" />
                  <path d="M-3 -3 L3 3 M-3 3 L3 -3" fill="none" stroke="white" strokeWidth={1.8} strokeLinecap="round" />
                </g>
              )}
            </g>
          );
        })}

        {/* ── Hover tooltip (foreignObject overlay) ───────────────────── */}
        {hoveredNode && nodeDetail && (() => {
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
            nodeDetail.level === "error" ? "#EF4444"
            : nodeDetail.level === "warning" ? "#F59E0B"
            : nodeDetail.level === "success" ? "#10B981"
            : "#6B7280";

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
                style={{
                  width: tipW,
                  fontFamily: "system-ui, sans-serif",
                }}
              >
                <div className="mb-2 flex items-center gap-2">
                  <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={badge.color} strokeWidth={2}>
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
                    state.chapterProgress[ch.name]?.done === state.chapterProgress[ch.name]?.total && state.chapterProgress[ch.name]?.total > 0
                      ? "#34D399"
                      : "#D1D5DB"
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
                chapFill = "#F0FDF4";
                chapStroke = "#34D399";
                chapText = "#065F46";
              } else if (isActive) {
                chapFill = "#ECFDF5";
                chapStroke = "#10B981";
                chapText = "#065F46";
              } else {
                chapFill = "#F9FAFB";
                chapStroke = "#D1D5DB";
                chapText = "#6B7280";
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
                    className="transition-all duration-500"
                    filter={isActive ? "url(#active-glow)" : undefined}
                  />
                  <rect
                    x={chapterX(i, chapterCount) + 4}
                    y={CHAPTER_START_Y + CHAPTER_H - 10}
                    width={CHAPTER_W - 8}
                    height={4}
                    rx={2}
                    fill="#E5E7EB"
                    className="dark:fill-ink-800"
                  />
                  {ratio > 0 && (
                    <rect
                      x={chapterX(i, chapterCount) + 4}
                      y={CHAPTER_START_Y + CHAPTER_H - 10}
                      width={(CHAPTER_W - 8) * ratio}
                      height={4}
                      rx={2}
                      fill={isDone ? "#34D399" : "#10B981"}
                      className="transition-all duration-700"
                    />
                  )}
                  <text
                    x={chapterX(i, chapterCount) + CHAPTER_W / 2}
                    y={CHAPTER_START_Y + 16}
                    textAnchor="middle"
                    fill={chapText}
                    fontSize={11}
                    fontWeight={600}
                    className="transition-colors duration-500"
                  >
                    {ch.name.length > 16 ? ch.name.slice(0, 15) + "…" : ch.name}
                  </text>
                  <text
                    x={chapterX(i, chapterCount) + CHAPTER_W / 2}
                    y={CHAPTER_START_Y + 30}
                    textAnchor="middle"
                    fill={isDone ? "#34D399" : isActive ? "#10B981" : "#9CA3AF"}
                    fontSize={10}
                    className="transition-colors duration-500"
                  >
                    {done}/{total} sections
                  </text>
                  {isDone && (
                    <g transform={`translate(${chapterX(i, chapterCount) + CHAPTER_W - 12}, ${CHAPTER_START_Y + 10})`}>
                      <circle r={7} fill="#10B981" />
                      <path d="M-3 0 L-1 2 L3 -2" fill="none" stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
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

/* ── Tooltip content helper ────────────────────────────────────────────── */

export function statusBadge(status: string): { color: string; label: string } {
  switch (status) {
    case "active": return { color: "#10B981", label: "Active" };
    case "completed": return { color: "#059669", label: "Completed" };
    case "error": return { color: "#EF4444", label: "Error" };
    default: return { color: "#9CA3AF", label: "Pending" };
  }
}
