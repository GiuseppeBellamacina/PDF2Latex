import type { ProgressEvent } from "../hooks/useGenerateWs";

/* ── Types ──────────────────────────────────────────────────────────────── */

export type NodeState = "pending" | "active" | "completed" | "error";

export interface GraphState {
  nodes: Record<string, NodeState>;
  chapters: ChapterInfo[];
  chapterProgress: Record<string, { done: number; total: number }>;
  errorNode: string | null;
  activeNodes: Set<string>;
  judgeRevising: boolean;
}

export interface ChapterInfo {
  name: string;
  sections: number;
}

export interface GraphNode {
  id: string;
  label: string;
  col: number;
  row: number;
}

export interface NodeDetail {
  title: string;
  status: string;
  lines: string[];
  level?: "info" | "success" | "warning" | "error";
}

/* ── Layout constants ──────────────────────────────────────────────────── */

export const NODE_W = 148;
export const NODE_H = 52;
export const CHAPTER_W = 130;
export const CHAPTER_H = 36;
export const COL_GAP = 80;
export const START_X = 24;
export const CENTER_Y = 160;
export const ROW_SPREAD = 94;

/* ── SVG colours ───────────────────────────────────────────────────────── */

export const COLORS = {
  node: {
    error:   { fill: "#FEF2F2", stroke: "#EF4444", text: "#991B1B", sub: "#DC2626" },
    active:  { fill: "#ECFDF5", stroke: "#10B981", text: "#065F46", sub: "#059669" },
    done:    { fill: "#F0FDF4", stroke: "#34D399", text: "#065F46", sub: "#10B981" },
    pending: { fill: "#F9FAFB", stroke: "#D1D5DB", text: "#6B7280", sub: "#9CA3AF" },
  },
  edgeActive:    { from: "#10B981", to: "#34D399" },
  edgeCompleted: { from: "#059669", to: "#10B981" },
  loopback: "#F59E0B",
  level: {
    error:   "#EF4444",
    warning: "#F59E0B",
    success: "#10B981",
    info:    "#6B7280",
  },
  glow: "#10B981",
  shadow: "#00000022",
  chapter: {
    done:      { fill: "#F0FDF4", stroke: "#34D399", text: "#065F46" },
    active:    { fill: "#ECFDF5", stroke: "#10B981", text: "#065F46" },
    pending:   { fill: "#F9FAFB", stroke: "#D1D5DB", text: "#6B7280" },
    progressBg: "#E5E7EB",
    connectorDone:    "#34D399",
    connectorPending: "#D1D5DB",
  },
} as const;

/* ── Main node layout ──────────────────────────────────────────────────── */

export const MAIN_NODES: GraphNode[] = [
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
export const POS: Record<string, [number, number]> = {};
for (const n of MAIN_NODES) POS[n.id] = [n.col, n.row];

/* ── Edge definitions: [from, to] ───────────────────────────────────────── */
export const EDGES: [string, string][] = [
  ["extract", "analyze"],
  ["research", "merge_analyses"],
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

/* ── Icons (simple SVG paths) ───────────────────────────────────────────── */

export const NODE_ICONS: Record<string, string> = {
  extract: "M4 4h16v4H4zM4 12h16v2H4zM4 18h12v2H4z",
  research:
    "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z",
  analyze:
    "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 010-5 2.5 2.5 0 010 5z",
  merge_analyses:
    "M18 10H6v2h12v-2zm-2 4H8v2h8v-2zm2-8H6v2h12V6zM3 18l4 2v-4l-4 2zm18 0l-4 2v-4l4 2z",
  plan: "M3 5h2V3H3v2zm4 0h10V3H7v2zm-4 6h2V9H3v2zm4 0h10V9H7v2zm-4 6h2v-2H3v2zm4 0h6v-2H7v2z",
  write:
    "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z",
  overview: "M4 6h16v2H4zm0 5h16v2H4zm0 5h12v2H4z",
  coherence: "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  citations: "M4 4h16v2H4zm0 4h16v2H4zm0 4h12v2H4zM4 4v12l4 4h12V4H4z",
  merge: "M8 3v18l8-9-8-9z",
  review:
    "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 2l5 5h-5V4zM8 13h8v2H8v-2zm0 4h8v2H8v-2zm0-8h3v2H8V9z",
  judge:
    "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z",
};

/* ── State derivation from events ──────────────────────────────────────── */

export function deriveState(events: ProgressEvent[]): GraphState {
  const nodes: Record<string, NodeState> = {};
  for (const n of MAIN_NODES) nodes[n.id] = "pending";

  const chapters: ChapterInfo[] = [];
  const chapterProgress: Record<string, { done: number; total: number }> = {};
  const activeNodes = new Set<string>();
  let errorNode: string | null = null;
  let judgeRevising = false;

  const order = [
    "extract",
    "research",
    "analyze",
    "merge_analyses",
    "plan",
    "write",
    "overview",
    "coherence",
    "citations",
    "merge",
    "review",
    "judge",
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
    if (
      e.chapter &&
      e.chapter_done !== undefined &&
      e.chapter_total !== undefined
    ) {
      chapterProgress[e.chapter] = {
        done: e.chapter_done,
        total: e.chapter_total,
      };
    }

    // Track judge revision action
    if (
      e.node === "judge" &&
      e.stage === "judging" &&
      e.detail &&
      e.detail.includes("Revisione")
    ) {
      judgeRevising = true;
    }
  }

  // Determine active nodes: all pending nodes whose predecessors are completed.
  for (const nid of order) {
    if (nodes[nid] !== "pending") continue;
    const idx = order.indexOf(nid);
    const allBeforeDone = order
      .slice(0, idx)
      .every((prev) => nodes[prev] === "completed");
    if (allBeforeDone) {
      activeNodes.add(nid);
    }
  }

  // Mark write as completed when all chapter sections are done.
  if (chapters.length > 0) {
    const allDone = chapters.every(
      (ch) =>
        chapterProgress[ch.name]?.done === chapterProgress[ch.name]?.total &&
        chapterProgress[ch.name]?.total > 0,
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

  return {
    nodes,
    chapters,
    chapterProgress,
    errorNode,
    activeNodes,
    judgeRevising,
  };
}

/* ── Node detail derivation from events ────────────────────────────────── */

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
      lines.push(
        `${filenames.length} document${filenames.length !== 1 ? "s" : ""}`,
      );
      for (const f of filenames.slice(0, 5)) lines.push(`  ▸ ${f}`);
      if (filenames.length > 5)
        lines.push(`  … +${filenames.length - 5} more`);
    }
    const errors = nodeEvents.filter((e) => e.level === "error");
    if (errors.length) {
      lines.push(
        `${errors.length} extraction error${errors.length !== 1 ? "s" : ""}`,
      );
      level = "warning";
    }
  } else if (nodeId === "research") {
    const tool = nodeEvents.find((e) => e.detail?.startsWith("tool:"))?.detail;
    if (tool) lines.push(`Using: ${tool.replace("tool: ", "")}`);
    const finish = nodeEvents.find((e) => e.level === "success");
    if (finish?.message) lines.push(finish.message);
    if (finish?.detail) lines.push(finish.detail);
    if (finish?.level === "success") level = "success";
    const warn = nodeEvents.find((e) => e.level === "warning");
    if (warn) {
      lines.push(warn.message);
      level = "warning";
    }
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
      lines.push(
        `${finish.plan.length} section${finish.plan.length !== 1 ? "s" : ""} planned`,
      );
      for (const s of finish.plan.slice(0, 4))
        lines.push(`  ▸ ${s.part_title} — ${s.title}`);
      if (finish.plan.length > 4)
        lines.push(`  … +${finish.plan.length - 4} more`);
    }
  } else if (nodeId === "write") {
    const chapEvent = nodeEvents.find((e) => e.action === "chapters_planned");
    if (chapEvent?.chapters) {
      lines.push(
        `${chapEvent.chapters.length} chapter${chapEvent.chapters.length !== 1 ? "s" : ""} in parallel`,
      );
      for (const ch of chapEvent.chapters) {
        const prog = state.chapterProgress[ch.name];
        const done = prog?.done ?? 0;
        const total = prog?.total ?? ch.sections;
        const icon =
          done === total && total > 0 ? "✓" : done > 0 ? "◐" : "○";
        lines.push(`  ${icon} ${ch.name} (${done}/${total})`);
        if (ch.sections > total)
          lines.push(`    ${ch.sections} sections total`);
      }
    }
    const sectionEvents = nodeEvents.filter(
      (e) => e.chapter_done !== undefined,
    );
    if (sectionEvents.length)
      lines.push(
        `${sectionEvents.length} section${sectionEvents.length !== 1 ? "s" : ""} written`,
      );
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
    const errorEvs = nodeEvents.filter(
      (e) => e.level === "error" || e.level === "warning",
    );
    if (successEv?.message) {
      lines.push(successEv.message);
      level = "success";
    }
    if (successEv?.tokens)
      lines.push(
        `${successEv.tokens.total_tokens.toLocaleString()} tokens · ${successEv.tokens.calls} LLM calls`,
      );
    for (const err of errorEvs.slice(0, 3))
      lines.push(err.detail ?? err.message);
    if (errorEvs.length && !successEv) level = "error";
  } else if (nodeId === "judge") {
    const verdict = nodeEvents.find((e) => e.level === "success");
    const warn = nodeEvents.find((e) => e.level === "warning");
    if (verdict) {
      lines.push(verdict.message);
      level = "success";
    }
    if (verdict?.detail) lines.push(verdict.detail);
    if (warn) {
      lines.push(warn.message);
      level = "warning";
    }
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

/* ── SVG layout helpers ────────────────────────────────────────────────── */

/** Absolute center-x of a node column. */
export function cx(col: number): number {
  return START_X + col * (NODE_W + COL_GAP) + NODE_W / 2;
}

/** Absolute center-y of a node row (row 0 = CENTER_Y). */
export function cy(row: number): number {
  return CENTER_Y + row * ROW_SPREAD;
}

/** Node top-left corner. */
export function x0(col: number): number {
  return cx(col) - NODE_W / 2;
}
export function y0(row: number): number {
  return cy(row) - NODE_H / 2;
}

/** Chapter sub-node positions: fan out below the write node. */
export const CHAPTER_START_Y = CENTER_Y + NODE_H / 2 + 28;
export const CHAPTER_ROW_H = CHAPTER_H + 10;

export function chapterX(index: number, total: number): number {
  const totalW = total * CHAPTER_W + (total - 1) * 10;
  const startX = cx(4) - totalW / 2;
  return startX + index * (CHAPTER_W + 10);
}

/** Compute a cubic bezier path string between two node centers. */
export function edgePath(
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
export function loopbackPath(): string {
  const jx = cx(8);
  const jy = cy(0) - NODE_H / 2;
  const rx = cx(7);
  const ry = cy(0) - NODE_H / 2;
  const midY = jy - 50;
  return `M ${jx} ${jy} C ${jx} ${midY}, ${rx} ${midY}, ${rx} ${ry}`;
}

/* ── Status badge ──────────────────────────────────────────────────────── */

export function statusBadge(
  status: string,
): { color: string; label: string } {
  switch (status) {
    case "active":
      return { color: COLORS.node.active.stroke, label: "Active" };
    case "completed":
      return { color: COLORS.node.done.stroke, label: "Completed" };
    case "error":
      return { color: COLORS.level.error, label: "Error" };
    default:
      return { color: COLORS.node.pending.sub, label: "Pending" };
  }
}
