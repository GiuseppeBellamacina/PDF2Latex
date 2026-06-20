import { describe, expect, it } from "vitest";
import type { ProgressEvent } from "../hooks/useGenerateWs";
import { deriveNodeDetails, deriveState, MAIN_NODES } from "./PipelineGraph.utils";

// ── deriveState ──────────────────────────────────────────────────────────

describe("deriveState", () => {
  it("initial state: all nodes pending", () => {
    const state = deriveState([]);
    for (const n of MAIN_NODES) {
      expect(state.nodes[n.id]).toBe("pending");
    }
    expect(state.chapters).toEqual([]);
    expect(state.errorNode).toBeNull();
    expect(state.judgeRevising).toBe(false);
  });

  it("marks a node completed on success event", () => {
    const events: ProgressEvent[] = [
      { stage: "extracting", node: "extract", level: "success", message: "ok" },
    ];
    const state = deriveState(events);
    expect(state.nodes["extract"]).toBe("completed");
  });

  it("marks a node as error and sets errorNode", () => {
    const events: ProgressEvent[] = [
      { stage: "extracting", node: "extract", level: "error", message: "fail" },
    ];
    const state = deriveState(events);
    expect(state.nodes["extract"]).toBe("error");
    expect(state.errorNode).toBe("extract");
  });

  it("auto-completes extract when analyze events arrive", () => {
    const events: ProgressEvent[] = [
      { stage: "analyzing", node: "analyze", level: "info", message: "start" },
    ];
    const state = deriveState(events);
    expect(state.nodes["extract"]).toBe("completed");
    expect(state.nodes["analyze"]).toBe("pending"); // not yet succeeded
  });

  it("auto-completes research when merge_analyses events arrive", () => {
    const events: ProgressEvent[] = [
      { stage: "merging", node: "merge_analyses", level: "info", message: "start" },
    ];
    const state = deriveState(events);
    expect(state.nodes["research"]).toBe("completed");
  });

  it("determines active nodes (pending with all predecessors done)", () => {
    const events: ProgressEvent[] = [
      { stage: "extracting", node: "extract", level: "success", message: "ok" },
      { stage: "researching", node: "research", level: "success", message: "ok" },
      { stage: "analyzing", node: "analyze", level: "success", message: "ok" },
    ];
    const state = deriveState(events);
    // extract, research, analyze all completed — merge_analyses is next pending
    expect(state.activeNodes.has("merge_analyses")).toBe(true);
    // completed nodes are no longer active
    expect(state.activeNodes.has("extract")).toBe(false);
    expect(state.activeNodes.has("research")).toBe(false);
    expect(state.activeNodes.has("analyze")).toBe(false);
  });

  it("does not activate nodes if a predecessor is still pending", () => {
    // Only extract completed; research is still pending → analyze NOT active
    const events: ProgressEvent[] = [
      { stage: "extracting", node: "extract", level: "success", message: "ok" },
    ];
    const state = deriveState(events);
    // research is next after extract (extract done, research pending → active)
    expect(state.activeNodes.has("research")).toBe(true);
    // analyze has research as predecessor which is still pending
    expect(state.activeNodes.has("analyze")).toBe(false);
    // merge_analyses also blocked
    expect(state.activeNodes.has("merge_analyses")).toBe(false);
  });

  it("populates chapters from chapters_planned action", () => {
    const events: ProgressEvent[] = [
      {
        stage: "planning",
        node: "plan",
        action: "chapters_planned",
        chapters: [
          { name: "Introduction", sections: 3 },
          { name: "Methods", sections: 2 },
        ],
        message: "planned",
      },
    ];
    const state = deriveState(events);
    expect(state.chapters).toHaveLength(2);
    expect(state.chapters[0]).toEqual({ name: "Introduction", sections: 3 });
    expect(state.chapterProgress["Introduction"]).toEqual({
      done: 0,
      total: 3,
    });
    expect(state.chapterProgress["Methods"]).toEqual({ done: 0, total: 2 });
  });

  it("tracks chapter progress", () => {
    const events: ProgressEvent[] = [
      {
        stage: "planning",
        node: "plan",
        action: "chapters_planned",
        chapters: [{ name: "Intro", sections: 3 }],
        message: "planned",
      },
      {
        stage: "writing",
        node: "write",
        chapter: "Intro",
        chapter_done: 2,
        chapter_total: 3,
        message: "writing",
      },
    ];
    const state = deriveState(events);
    expect(state.chapterProgress["Intro"]).toEqual({ done: 2, total: 3 });
  });

  it("auto-completes write when all chapters are fully written", () => {
    const events: ProgressEvent[] = [
      {
        stage: "planning",
        node: "plan",
        action: "chapters_planned",
        chapters: [{ name: "A", sections: 2 }],
        message: "planned",
      },
      {
        stage: "writing",
        node: "write",
        chapter: "A",
        chapter_done: 2,
        chapter_total: 2,
        message: "done",
      },
    ];
    const state = deriveState(events);
    expect(state.nodes["write"]).toBe("completed");
  });

  it("does NOT auto-complete write if chapters are partially done", () => {
    const events: ProgressEvent[] = [
      {
        stage: "planning",
        node: "plan",
        action: "chapters_planned",
        chapters: [{ name: "A", sections: 3 }],
        message: "planned",
      },
      {
        stage: "writing",
        node: "write",
        chapter: "A",
        chapter_done: 1,
        chapter_total: 3,
        message: "writing",
      },
    ];
    const state = deriveState(events);
    expect(state.nodes["write"]).toBe("pending");
  });

  it("auto-completes diamond nodes when merge is completed", () => {
    const events: ProgressEvent[] = [
      { stage: "extracting", node: "extract", level: "success", message: "ok" },
      { stage: "analyzing", node: "analyze", level: "success", message: "ok" },
      { stage: "merging", node: "merge_analyses", level: "success", message: "ok" },
      { stage: "planning", node: "plan", level: "success", message: "ok" },
      { stage: "writing", node: "write", level: "success", message: "ok" },
      { stage: "reviewing", node: "overview", level: "info", message: "start" },
      { stage: "reviewing", node: "coherence", level: "info", message: "start" },
      { stage: "merging", node: "merge", level: "success", message: "ok" },
    ];
    const state = deriveState(events);
    expect(state.nodes["overview"]).toBe("completed");
    expect(state.nodes["coherence"]).toBe("completed");
    expect(state.nodes["citations"]).toBe("completed");
  });

  it("clears active nodes after errorNode", () => {
    const events: ProgressEvent[] = [
      { stage: "extracting", node: "extract", level: "success", message: "ok" },
      { stage: "analyzing", node: "analyze", level: "success", message: "ok" },
      { stage: "merging", node: "merge_analyses", level: "error", message: "fail" },
    ];
    const state = deriveState(events);
    expect(state.errorNode).toBe("merge_analyses");
    // active nodes after merge_analyses (plan, write, etc.) should NOT be active
    expect(state.activeNodes.has("plan")).toBe(false);
    expect(state.activeNodes.has("write")).toBe(false);
  });

  it("detects judge revision when detail contains 'Revisione'", () => {
    const events: ProgressEvent[] = [
      {
        stage: "judging",
        node: "judge",
        level: "info",
        message: "Need fixes",
        detail: "Revisione richiesta: struttura",
      },
    ];
    const state = deriveState(events);
    expect(state.judgeRevising).toBe(true);
  });

  it("does NOT set judgeRevising for regular judge events", () => {
    const events: ProgressEvent[] = [
      {
        stage: "judging",
        node: "judge",
        level: "success",
        message: "All good",
        detail: "Documento approvato",
      },
    ];
    const state = deriveState(events);
    expect(state.judgeRevising).toBe(false);
  });

  it("handles multiple success events in pipeline order", () => {
    const events: ProgressEvent[] = [
      { stage: "extracting", node: "extract", level: "success", message: "ok" },
      { stage: "researching", node: "research", level: "success", message: "ok" },
      { stage: "analyzing", node: "analyze", level: "success", message: "ok" },
      { stage: "merging", node: "merge_analyses", level: "success", message: "ok" },
    ];
    const state = deriveState(events);
    expect(state.nodes["extract"]).toBe("completed");
    expect(state.nodes["research"]).toBe("completed");
    expect(state.nodes["analyze"]).toBe("completed");
    expect(state.nodes["merge_analyses"]).toBe("completed");
    // next active should be plan
    expect(state.activeNodes.has("plan")).toBe(true);
  });

  it("write stays pending when chapters is empty (no chapters_planned)", () => {
    const events: ProgressEvent[] = [
      { stage: "writing", node: "write", level: "info", message: "writing" },
    ];
    const state = deriveState(events);
    expect(state.nodes["write"]).toBe("pending"); // chapters.length === 0, so no auto-complete
  });

  it("null node events are ignored gracefully", () => {
    const events: ProgressEvent[] = [
      { stage: "starting", message: "Starting pipeline" },
    ];
    const state = deriveState(events);
    // all nodes remain pending
    for (const n of MAIN_NODES) {
      expect(state.nodes[n.id]).toBe("pending");
    }
  });
});

// ── deriveNodeDetails ────────────────────────────────────────────────────

describe("deriveNodeDetails", () => {
  const pendingState = deriveState([]);

  it("returns correct title for each known node", () => {
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
    for (const [id, label] of Object.entries(labels)) {
      const detail = deriveNodeDetails(id, [], pendingState);
      expect(detail).not.toBeNull();
      expect(detail!.title).toBe(label);
    }
  });

  it("returns fallback for unknown node id", () => {
    const detail = deriveNodeDetails("unknown_node", [], pendingState);
    // The function always returns an object; title falls back to nodeId
    expect(detail!.title).toBe("unknown_node");
    expect(detail!.status).toBe("pending");
    expect(detail!.lines).toEqual(["Waiting to start…"]);
  });

  describe("extract node", () => {
    it("shows filenames from extraction messages", () => {
      const events: ProgressEvent[] = [
        {
          stage: "extracting",
          node: "extract",
          message: "Estrazione main.pdf (1/3)",
          level: "info",
        },
        {
          stage: "extracting",
          node: "extract",
          message: "Estrazione appendix.pdf (2/3)",
          level: "info",
        },
        {
          stage: "extracting",
          node: "extract",
          message: "Estrazione refs.pdf (3/3)",
          level: "info",
        },
      ];
      const detail = deriveNodeDetails("extract", events, pendingState);
      expect(detail!.lines).toContain("3 documents");
      expect(detail!.lines).toContain("  ▸ main.pdf");
      expect(detail!.lines).toContain("  ▸ appendix.pdf");
      expect(detail!.lines).toContain("  ▸ refs.pdf");
    });

    it("truncates filenames beyond 6 with ellipsis", () => {
      const events: ProgressEvent[] = Array.from({ length: 8 }, (_, i) => ({
        stage: "extracting",
        node: "extract",
        message: `Estrazione doc${i}.pdf (${i + 1}/8)`,
        level: "info" as const,
      }));
      const detail = deriveNodeDetails("extract", events, pendingState);
      expect(detail!.lines).toContain("8 documents");
      expect(detail!.lines).toContain("  … +2 more");
    });

    it("shows extraction errors", () => {
      const events: ProgressEvent[] = [
        {
          stage: "extracting",
          node: "extract",
          message: "Estrazione bad.pdf (1/2)",
          level: "info",
        },
        {
          stage: "extracting",
          node: "extract",
          message: "Errore",
          level: "error",
        },
      ];
      const detail = deriveNodeDetails("extract", events, pendingState);
      expect(detail!.lines).toContain("1 extraction error");
      expect(detail!.level).toBe("warning");
    });
  });

  describe("research node", () => {
    it("shows tool from detail", () => {
      const events: ProgressEvent[] = [
        {
          stage: "researching",
          node: "research",
          detail: "tool: wikipedia",
          level: "info",
          message: "Starting research",
        },
      ];
      const detail = deriveNodeDetails("research", events, pendingState);
      expect(detail!.lines.some((l) => l.includes("wikipedia"))).toBe(true);
    });

    it("shows success finish message and detail", () => {
      const events: ProgressEvent[] = [
        {
          stage: "researching",
          node: "research",
          level: "success",
          message: "Research complete",
          detail: "3 sources found",
        },
      ];
      const detail = deriveNodeDetails("research", events, pendingState);
      expect(detail!.lines).toContain("Research complete");
      expect(detail!.lines).toContain("3 sources found");
      expect(detail!.level).toBe("success");
    });

    it("shows warning from warning-level event", () => {
      const events: ProgressEvent[] = [
        {
          stage: "researching",
          node: "research",
          level: "warning",
          message: "No results found",
        },
      ];
      const detail = deriveNodeDetails("research", events, pendingState);
      expect(detail!.lines).toContain("No results found");
      expect(detail!.level).toBe("warning");
    });
  });

  describe("analyze node", () => {
    it("shows processed documents", () => {
      const events: ProgressEvent[] = [
        {
          stage: "analyzing",
          node: "analyze",
          documents: ["main.pdf", "appendix.pdf"],
          level: "info",
          message: "Starting analysis",
        },
      ];
      const detail = deriveNodeDetails("analyze", events, pendingState);
      expect(detail!.lines).toContain("2 documents analyzed");
      expect(detail!.lines).toContain("  ▸ main.pdf");
      expect(detail!.lines).toContain("  ▸ appendix.pdf");
    });

    it("shows finish detail", () => {
      const events: ProgressEvent[] = [
        {
          stage: "analyzing",
          node: "analyze",
          level: "success",
          detail: "3 sections identified",
          message: "Done",
        },
      ];
      const detail = deriveNodeDetails("analyze", events, pendingState);
      expect(detail!.lines).toContain("3 sections identified");
    });
  });

  describe("merge_analyses node", () => {
    it("shows event message and detail", () => {
      const events: ProgressEvent[] = [
        {
          stage: "merging",
          node: "merge_analyses",
          level: "success",
          message: "Merged 3 analyses",
          detail: "Combined results",
        },
      ];
      const detail = deriveNodeDetails("merge_analyses", events, pendingState);
      expect(detail!.lines).toContain("Merged 3 analyses");
      expect(detail!.lines).toContain("Combined results");
      expect(detail!.level).toBe("success");
    });
  });

  describe("plan node", () => {
    it("shows sections planned from success plan event", () => {
      const events: ProgressEvent[] = [
        {
          stage: "planning",
          node: "plan",
          level: "success",
          message: "Plan ready",
          plan: [
            { part_title: "Part I", title: "Introduction" },
            { part_title: "Part II", title: "Methods" },
          ],
        },
      ];
      const detail = deriveNodeDetails("plan", events, pendingState);
      expect(detail!.lines).toContain("2 sections planned");
      expect(detail!.lines).toContain("  ▸ Part I — Introduction");
      expect(detail!.lines).toContain("  ▸ Part II — Methods");
    });

    it("truncates sections beyond 5", () => {
      const plan = Array.from({ length: 7 }, (_, i) => ({
        part_title: `Part ${i}`,
        title: `Section ${i}`,
      }));
      const events: ProgressEvent[] = [
        {
          stage: "planning",
          node: "plan",
          level: "success",
          message: "Plan ready",
          plan,
        },
      ];
      const detail = deriveNodeDetails("plan", events, pendingState);
      expect(detail!.lines).toContain("7 sections planned");
      expect(detail!.lines).toContain("  … +2 more");
    });
  });

  describe("write node", () => {
    it("shows chapters with progress icons", () => {
      const events: ProgressEvent[] = [
        {
          stage: "planning",
          node: "write",
          action: "chapters_planned",
          chapters: [
            { name: "Intro", sections: 2 },
            { name: "Methods", sections: 3 },
          ],
          message: "planned",
        },
        {
          stage: "writing",
          node: "write",
          chapter: "Intro",
          chapter_done: 2,
          chapter_total: 2,
          message: "done",
        },
        {
          stage: "writing",
          node: "write",
          chapter: "Methods",
          chapter_done: 1,
          chapter_total: 3,
          message: "writing",
        },
      ];
      const state = deriveState(events);
      const detail = deriveNodeDetails("write", events, state);
      expect(detail!.lines).toContain("2 chapters in parallel");
      expect(detail!.lines).toContain("  ✓ Intro  2/2 (100%)");
      expect(detail!.lines).toContain("  ◐ Methods  1/3 (33%)");
    });

    it("shows sections written count", () => {
      const events: ProgressEvent[] = [
        {
          stage: "writing",
          node: "write",
          chapter: "Intro",
          chapter_done: 1,
          chapter_total: 3,
          message: "writing",
        },
        {
          stage: "writing",
          node: "write",
          chapter: "Intro",
          chapter_done: 2,
          chapter_total: 3,
          message: "writing",
        },
      ];
      const state = deriveState(events);
      const detail = deriveNodeDetails("write", events, state);
      expect(detail!.lines).toContain("2 sections written");
    });

    it("shows expanding action", () => {
      const events: ProgressEvent[] = [
        {
          stage: "writing",
          node: "write",
          action: "expanding",
          detail: "Section 3.2 — Results",
          message: "expanding",
        },
      ];
      const state = deriveState(events);
      const detail = deriveNodeDetails("write", events, state);
      expect(detail!.lines.some((l) => l.includes("Expanding"))).toBe(true);
    });
  });

  describe("coherence node", () => {
    it("shows event message and detail", () => {
      const events: ProgressEvent[] = [
        {
          stage: "reviewing",
          node: "coherence",
          level: "info",
          message: "Checking flow",
          detail: "2 issues found",
        },
      ];
      const detail = deriveNodeDetails("coherence", events, pendingState);
      expect(detail!.lines).toContain("Checking flow");
      expect(detail!.lines).toContain("2 issues found");
    });

    it("sets level to warning/error from event", () => {
      const events: ProgressEvent[] = [
        {
          stage: "reviewing",
          node: "coherence",
          level: "error",
          message: "Critical gap",
          detail: "Structural discontinuity",
        },
      ];
      const detail = deriveNodeDetails("coherence", events, pendingState);
      expect(detail!.level).toBe("error");
    });
  });

  describe("citations node", () => {
    it("shows event message and detail", () => {
      const events: ProgressEvent[] = [
        {
          stage: "reviewing",
          node: "citations",
          level: "warning",
          message: "Missing citations",
          detail: "3 references not found",
        },
      ];
      const detail = deriveNodeDetails("citations", events, pendingState);
      expect(detail!.lines).toContain("Missing citations");
      expect(detail!.lines).toContain("3 references not found");
      expect(detail!.level).toBe("warning");
    });
  });

  describe("overview node", () => {
    it("shows success message", () => {
      const events: ProgressEvent[] = [
        {
          stage: "reviewing",
          node: "overview",
          level: "success",
          message: "Overview complete",
        },
      ];
      const detail = deriveNodeDetails("overview", events, pendingState);
      expect(detail!.lines).toContain("Overview complete");
    });
  });

  describe("merge node", () => {
    it("shows merge event details", () => {
      const events: ProgressEvent[] = [
        {
          stage: "merging",
          node: "merge",
          level: "info",
          message: "Merging sections",
          detail: "Combining chapters",
        },
      ];
      const detail = deriveNodeDetails("merge", events, pendingState);
      expect(detail!.lines).toContain("Merging sections");
      expect(detail!.lines).toContain("Combining chapters");
    });
  });

  describe("review node", () => {
    it("shows success message with tokens", () => {
      const events: ProgressEvent[] = [
        {
          stage: "reviewing",
          node: "review",
          level: "success",
          message: "Review passed",
          tokens: {
            calls: 5,
            input_tokens: 1000,
            output_tokens: 500,
            total_tokens: 1500,
          },
        },
      ];
      const detail = deriveNodeDetails("review", events, pendingState);
      expect(detail!.lines).toContain("Review passed");
      expect(detail!.level).toBe("success");
    });

    it("shows errors when no success event", () => {
      const events: ProgressEvent[] = [
        {
          stage: "reviewing",
          node: "review",
          level: "error",
          message: "Fatal error",
          detail: "Compilation failed",
        },
      ];
      const detail = deriveNodeDetails("review", events, pendingState);
      expect(detail!.level).toBe("error");
      expect(detail!.lines).toContain("Compilation failed");
    });
  });

  describe("judge node", () => {
    it("shows verdict message", () => {
      const events: ProgressEvent[] = [
        {
          stage: "judging",
          node: "judge",
          level: "success",
          message: "Score: 8.5",
          judge_score: 8.5,
        },
      ];
      const detail = deriveNodeDetails("judge", events, pendingState);
      expect(detail!.lines).toContain("Score: 8.5");
      expect(detail!.level).toBe("success");
    });

    it("shows revision note from state", () => {
      const state = deriveState([
        {
          stage: "judging",
          node: "judge",
          level: "info",
          message: "Check",
          detail: "Revisione necessaria",
        },
      ]);
      const events: ProgressEvent[] = [
        {
          stage: "judging",
          node: "judge",
          level: "info",
          message: "Check",
          detail: "Revisione necessaria",
        },
      ];
      const detail = deriveNodeDetails("judge", events, state);
      expect(detail!.lines).toContain("↻ Requested structural revision");
    });

    it("shows warning details", () => {
      const events: ProgressEvent[] = [
        {
          stage: "judging",
          node: "judge",
          level: "warning",
          message: "Minor issues",
          detail: "Some citations missing",
        },
      ];
      const detail = deriveNodeDetails("judge", events, pendingState);
      expect(detail!.lines).toContain("Minor issues");
      expect(detail!.lines).toContain("Some citations missing");
      expect(detail!.level).toBe("warning");
    });
  });

  describe("fallback messages", () => {
    it('shows "Waiting to start…" for pending nodes with no events', () => {
      const detail = deriveNodeDetails("extract", [], pendingState);
      expect(detail!.lines).toEqual(["Waiting to start…"]);
    });

    it('shows "Waiting to start…" for active nodes with no events (status stays pending)', () => {
      // After extract completes, research becomes active (all predecessors done)
      // but its state.nodes["research"] is still "pending", so fallback says "Waiting to start…"
      const state = deriveState([
        {
          stage: "extracting",
          node: "extract",
          level: "success",
          message: "ok",
        },
      ]);
      expect(state.activeNodes.has("research")).toBe(true);
      const detail = deriveNodeDetails("research", [], state);
      expect(detail!.lines).toEqual(["Waiting to start…"]);
      expect(detail!.status).toBe("pending");
    });

    it('shows "Completed" for completed nodes with no extra info', () => {
      const state = deriveState([
        {
          stage: "extracting",
          node: "extract",
          level: "success",
          message: "ok",
        },
      ]);
      // "extract" with no filename messages → no lines extracted → falls back
      const detail = deriveNodeDetails("extract", [], state);
      expect(detail!.lines).toEqual(["Completed"]);
      expect(detail!.status).toBe("completed");
    });

    it('shows "Failed" for error nodes', () => {
      const state = deriveState([
        {
          stage: "extracting",
          node: "extract",
          level: "error",
          message: "fail",
        },
      ]);
      const detail = deriveNodeDetails("extract", [], state);
      expect(detail!.lines).toEqual(["Failed"]);
      expect(detail!.status).toBe("error");
    });
  });
});
