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
  /** Extra structured data for rich tooltip rendering */
  researchSources?: { title: string; url: string; source: string }[];
  analyzeDocuments?: string[];
  chapterDetails?: { name: string; done: number; total: number }[];
  errorDetail?: string;
}

export interface PhaseInfo {
  currentPhase: string;
  currentIcon: string;
  progress: number; // 0–100
  phaseIndex: number; // 0-based step number
  totalPhases: number;
  activeNodeIds: string[];
  completedCount: number;
  totalCount: number;
}

/* ── Layout constants ──────────────────────────────────────────────────── */

export const NODE_W = 210;
export const NODE_H = 74;
export const CHAPTER_W = 180;
export const CHAPTER_H = 50;
export const COL_GAP = 80;
export const START_X = 32;
export const CENTER_Y = 240;
export const ROW_SPREAD = 130;

/* ── Derived layout helpers ────────────────────────────────────────────── */

/** Total phases for progress calculation (main nodes only) */
export const PHASE_ORDER = [
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

/** Human-readable phase step labels */
export const PHASE_LABELS: Record<string, string> = {
  extract: "Extraction",
  research: "Web Research",
  analyze: "Document Analysis",
  merge_analyses: "Source Merge",
  plan: "Outline Planning",
  write: "Chapter Writing",
  overview: "Overview",
  coherence: "Coherence",
  citations: "Citations",
  merge: "Final Merge",
  review: "LaTeX Review",
  judge: "Quality Judge",
};

/* ── SVG colours ───────────────────────────────────────────────────────── */

/**
 * Colors as CSS custom property references.
 * These resolve to the correct light/dark value via index.css :root / .dark vars.
 */
export const COLORS = {
  node: {
    error:   { fill: "var(--pg-node-error-fill)", stroke: "var(--pg-node-error-stroke)", text: "var(--pg-node-error-text)", sub: "var(--pg-node-error-sub)" },
    active:  { fill: "var(--pg-node-active-fill)", stroke: "var(--pg-node-active-stroke)", text: "var(--pg-node-active-text)", sub: "var(--pg-node-active-sub)" },
    done:    { fill: "var(--pg-node-done-fill)", stroke: "var(--pg-node-done-stroke)", text: "var(--pg-node-done-text)", sub: "var(--pg-node-done-sub)" },
    pending: { fill: "var(--pg-node-pending-fill)", stroke: "var(--pg-node-pending-stroke)", text: "var(--pg-node-pending-text)", sub: "var(--pg-node-pending-sub)" },
  },
  edgeActive:    { from: "var(--pg-edge-active-from)", to: "var(--pg-edge-active-to)" },
  edgeCompleted: { from: "var(--pg-edge-completed-from)", to: "var(--pg-edge-completed-to)" },
  loopback: "var(--pg-loopback)",
  level: {
    error:   "#EF4444",
    warning: "#F59E0B",
    success: "#10B981",
    info:    "#6B7280",
  },
  glow: "var(--pg-glow)",
  shadow: "var(--pg-shadow)",
  chapter: {
    done:      { fill: "var(--pg-ch-done-fill)", stroke: "var(--pg-ch-done-stroke)", text: "var(--pg-ch-done-text)" },
    active:    { fill: "var(--pg-ch-active-fill)", stroke: "var(--pg-ch-active-stroke)", text: "var(--pg-ch-active-text)" },
    pending:   { fill: "var(--pg-ch-pending-fill)", stroke: "var(--pg-ch-pending-stroke)", text: "var(--pg-ch-pending-text)" },
    progressBg: "var(--pg-ch-progress-bg)",
    connectorDone:    "var(--pg-ch-connector-done)",
    connectorPending: "var(--pg-ch-connector-pending)",
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

  for (const e of events) {
    const nid = e.node;
    if (nid && nodes[nid] !== undefined) {
      if (e.level === "error") {
        nodes[nid] = "error";
        errorNode = nid;
      } else if (e.level === "success" || e.level === "warning") {
        // Warning means the node finished its work (possibly with issues).
        // The warning color still renders in the UI to signal imperfect results.
        nodes[nid] = "completed";
      }
    }

    // Backend guarantees that sending a "success" event for extract, research,
    // or analyze marks them completed. In addition, infer completion when
    // downstream nodes start (robustness against missing success events).
    // Mark extract as completed when analyze events start arriving.
    if (e.node === "analyze" && nodes["extract"] === "pending") {
      nodes["extract"] = "completed";
    }
    // Mark research as completed when merge_analyses events arrive.
    if (e.node === "merge_analyses" && nodes["research"] === "pending") {
      nodes["research"] = "completed";
    }
    // Mark diamond nodes (overview, coherence, citations) completed
    // when merge events arrive.
    if (e.node === "merge") {
      for (const d of ["overview", "coherence", "citations"]) {
        if (nodes[d] === "pending") nodes[d] = "completed";
      }
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

  // Build predecessor map from EDGES (which reflects the actual DAG topology).
  const predecessors: Record<string, string[]> = {};
  for (const n of MAIN_NODES) predecessors[n.id] = [];
  for (const [from, to] of EDGES) {
    predecessors[to].push(from);
  }

  // Detect active nodes: a pending node is active when ALL its predecessors
  // are completed. This correctly handles parallel branches (research+analyze
  // both become active after extract completes) and the diamond merge.
  for (const nid of PHASE_ORDER) {
    if (nodes[nid] !== "pending") continue;
    const allPredsDone = (predecessors[nid] ?? []).every(
      (p) => nodes[p] === "completed",
    );
    if (allPredsDone) {
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

  // If any node errored, clear downstream active nodes.
  if (errorNode) {
    // Find all nodes reachable after errorNode in the DAG
    const reachable = new Set<string>();
    const queue = [errorNode];
    while (queue.length > 0) {
      const cur = queue.shift()!;
      for (const [from, to] of EDGES) {
        if (from === cur && !reachable.has(to)) {
          reachable.add(to);
          queue.push(to);
        }
      }
    }
    for (const nid of activeNodes) {
      if (reachable.has(nid)) activeNodes.delete(nid);
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
    analyze: "Document Analysis",
    merge_analyses: "Source Merge",
    plan: "Outline Planning",
    write: "Chapter Writing",
    overview: "Overview",
    coherence: "Coherence Check",
    citations: "Citation Review",
    merge: "Final Merge",
    review: "LaTeX Review",
    judge: "Quality Judge",
  };
  const lines: string[] = [];
  let level: "info" | "success" | "warning" | "error" = "info";

  // Extra structured data for rich rendering
  let researchSources: { title: string; url: string; source: string }[] | undefined;
  let analyzeDocuments: string[] | undefined;
  let chapterDetails: { name: string; done: number; total: number }[] | undefined;
  let errorDetail: string | undefined;

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
      for (const f of filenames.slice(0, 6)) lines.push(`  ▸ ${f}`);
      if (filenames.length > 6)
        lines.push(`  … +${filenames.length - 6} more`);
    }
    const errors = nodeEvents.filter((e) => e.level === "error");
    if (errors.length) {
      lines.push(
        `${errors.length} extraction error${errors.length !== 1 ? "s" : ""}`,
      );
      level = "warning";
    }
  } else if (nodeId === "research") {
    // Collect research_results from events carrying that field
    const allSources: { title: string; url: string; source: string }[] = [];
    const adapters: string[] = [];
    let iterationCount = 0;

    for (const e of nodeEvents) {
      if (e.research_results?.length) {
        allSources.push(...e.research_results);
      }
      if (e.detail?.startsWith("tool:")) {
        const tool = e.detail.replace("tool:", "").trim();
        if (!adapters.includes(tool)) adapters.push(tool);
      }
      if (e.detail?.startsWith("iteration:") || e.message?.startsWith("Iteration")) {
        iterationCount++;
      }
    }

    if (allSources.length > 0) {
      researchSources = allSources;
      lines.push(`${allSources.length} source${allSources.length !== 1 ? "s" : ""} found`);
      for (const src of allSources.slice(0, 5)) {
        const label = src.title.length > 55 ? src.title.slice(0, 54) + "…" : src.title;
        lines.push(`  ▸ ${label}`);
      }
      if (allSources.length > 5) {
        lines.push(`  … +${allSources.length - 5} more`);
      }
    }

    if (iterationCount > 0) {
      lines.push(`  ${iterationCount} web iteration${iterationCount !== 1 ? "s" : ""}`);
    }

    if (adapters.length > 0) {
      lines.push(`  Adapters: ${adapters.join(", ")}`);
    }

    const finish = nodeEvents.find((e) => e.level === "success");
    if (finish?.message && !allSources.length) {
      lines.push(finish.message);
    }
    if (finish?.detail && !finish.detail.startsWith("tool:")) {
      lines.push(finish.detail);
    }
    if (finish?.level === "success") level = "success";

    const warn = nodeEvents.find((e) => e.level === "warning");
    if (warn) {
      lines.push(warn.message);
      level = "warning";
    }
  } else if (nodeId === "analyze") {
    // Collect documents analyzed
    const docs: string[] = [];
    for (const e of nodeEvents) {
      if (e.documents?.length) {
        for (const d of e.documents) {
          if (!docs.includes(d)) docs.push(d);
        }
      }
    }
    if (docs.length > 0) {
      analyzeDocuments = docs;
      lines.push(`${docs.length} document${docs.length !== 1 ? "s" : ""} analyzed`);
      for (const d of docs.slice(0, 4)) lines.push(`  ▸ ${d}`);
      if (docs.length > 4) lines.push(`  … +${docs.length - 4} more`);
    }

    // Extract topic/formula/figure counts from detail messages
    const topicMatch = nodeEvents.find((e) => e.detail?.match(/topic|section|argomento/i));
    if (topicMatch?.detail) {
      if (!topicMatch.detail.startsWith("tool:")) {
        lines.push(`  Info: ${topicMatch.detail}`);
      }
    }

    const finish = nodeEvents.find((e) => e.level === "success");
    if (finish?.detail && docs.length === 0) lines.push(finish.detail);
    if (finish?.level === "success") level = "success";
  } else if (nodeId === "merge_analyses") {
    const ev = nodeEvents.find((e) => e.node === "merge_analyses");
    if (ev?.message) lines.push(ev.message);
    if (ev?.detail && !ev.detail.startsWith("tool:")) lines.push(ev.detail);
    if (ev?.level === "success") level = "success";
  } else if (nodeId === "plan") {
    const finish = nodeEvents.find((e) => e.level === "success" && e.plan);
    if (finish?.plan) {
      lines.push(
        `${finish.plan.length} section${finish.plan.length !== 1 ? "s" : ""} planned`,
      );
      for (const s of finish.plan.slice(0, 5))
        lines.push(`  ▸ ${s.part_title} — ${s.title}`);
      if (finish.plan.length > 5)
        lines.push(`  … +${finish.plan.length - 5} more`);
    }
  } else if (nodeId === "write") {
    const chapEvent = nodeEvents.find((e) => e.action === "chapters_planned");
    if (chapEvent?.chapters) {
      const details: { name: string; done: number; total: number }[] = [];
      lines.push(
        `${chapEvent.chapters.length} chapter${chapEvent.chapters.length !== 1 ? "s" : ""} in parallel`,
      );
      for (const ch of chapEvent.chapters) {
        const prog = state.chapterProgress[ch.name];
        const done = prog?.done ?? 0;
        const total = prog?.total ?? ch.sections;
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        const icon =
          done === total && total > 0 ? "✓" : done > 0 ? "◐" : "○";
        lines.push(`  ${icon} ${ch.name}  ${done}/${total} (${pct}%)`);
        details.push({ name: ch.name, done, total });
      }
      chapterDetails = details;
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
    if (ev?.detail && !ev.detail.startsWith("tool:")) lines.push(ev.detail);
    if (ev?.level === "warning") level = "warning";
    if (ev?.level === "error") level = "error";
  } else if (nodeId === "citations") {
    const ev = nodeEvents.find((e) => e.detail);
    if (ev?.message) lines.push(ev.message);
    if (ev?.detail && !ev.detail.startsWith("tool:")) lines.push(ev.detail);
    if (ev?.level === "warning") level = "warning";
  } else if (nodeId === "overview") {
    const ev = nodeEvents.find((e) => e.level === "success");
    if (ev?.message) lines.push(ev.message);
    const start = nodeEvents.find((e) => e.progress === 81);
    if (start?.message) lines.push(start.message);
  } else if (nodeId === "merge") {
    const ev = nodeEvents.find((e) => e.node === "merge");
    if (ev?.message) lines.push(ev.message);
    if (ev?.detail && !ev.detail.startsWith("tool:")) lines.push(ev.detail);
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
    for (const err of errorEvs.slice(0, 3)) {
      const msg = err.detail ?? err.message;
      lines.push(msg);
      // Capture LaTeX error details for rich display
      if (err.level === "error" && msg) {
        errorDetail = errorDetail
          ? errorDetail + "\n" + msg
          : msg;
      }
    }
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
    // A node that is pending but in activeNodes is conceptually "in progress"
    const isActive = status === "pending" && state.activeNodes.has(nodeId);
    if (isActive) lines.push("In progress…");
    else if (status === "pending") lines.push("Waiting to start…");
    else if (status === "completed") lines.push("Completed");
    else if (status === "error") lines.push("Failed");
  }

  return {
    title: labels[nodeId] ?? nodeId,
    status,
    lines,
    level,
    researchSources,
    analyzeDocuments,
    chapterDetails,
    errorDetail,
  };
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

/** Chapter sub-node positions: fan out below the lowest main node (row=1). */
const maxRow = Math.max(...MAIN_NODES.map((n) => n.row));
export const CHAPTER_START_Y = CENTER_Y + maxRow * ROW_SPREAD + NODE_H / 2 + 40;
export const CHAPTER_ROW_H = CHAPTER_H + 12;

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

/* ── Phase info derivation ─────────────────────────────────────────────── */

export function derivePhaseInfo(state: GraphState): PhaseInfo {
  const completedCount = PHASE_ORDER.filter(
    (id) => state.nodes[id] === "completed",
  ).length;
  const totalCount = PHASE_ORDER.length;
  const progress = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  // Determine the current phase: last active in order, or first pending
  let currentId = PHASE_ORDER[PHASE_ORDER.length - 1]; // default: last
  for (const id of PHASE_ORDER) {
    if (state.nodes[id] === "active") {
      currentId = id;
      break;
    }
    if (state.nodes[id] === "pending" && currentId === PHASE_ORDER[PHASE_ORDER.length - 1]) {
      currentId = id;
    }
  }

  // Error overrides
  if (state.errorNode) {
    currentId = state.errorNode;
  }

  const activeNodeIds = [...state.activeNodes];

  return {
    currentPhase: PHASE_LABELS[currentId] ?? currentId,
    currentIcon: NODE_ICONS[currentId] ?? "",
    progress,
    // phaseIndex tracks completedCount + 1 so it never diverges from progress bar
    phaseIndex: Math.min(completedCount + 1, totalCount),
    totalPhases: totalCount,
    activeNodeIds,
    completedCount,
    totalCount,
  };
}
