"""End-to-end test: full graph execution with all nodes mocked.

Verifies that ``build_graph().ainvoke()`` completes the full diamond-pattern
pipeline (analyze → plan → write → fan-out → merge → review → judge → END)
without any real LLM calls or file I/O.

Every external dependency is mocked:
- LLM calls: analyze_document, plan_document, write_section,
  summarize_section_context, call_llm_structured, check_coherence,
  audit_citations, judge_structure
- File I/O / compilation: write_and_compile
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph import build_graph
from app.agents.state import GraphState

# ── Mock helpers ───────────────────────────────────────────────────────────


class _MockVerdict:
    """Simulate a judge verdict with approved=True so the graph terminates."""

    approved: bool = True
    score: int = 92
    issues: list[str] = []
    summary: str = "Documento ben strutturato"


class _MockChapter:
    """Simulate a single overview chapter entry."""

    part_title: str = "Capitolo 1"
    synopsis: str = "Sintesi del capitolo"


class _MockOverviewVerdict:
    """Simulate the structured overview response."""

    chapters: list[_MockChapter] = [_MockChapter()]


@dataclass
class _MockCompileResult:
    """Simulate a successful compilation."""

    success: bool = True
    pdf_path: str | None = "/tmp/output/main.pdf"
    log: str = "Output written on main.pdf (1 page)."


_LONG_LATEX = (
    "\\section{Introduzione}\n"
    + "Il machine learning è un campo dell'intelligenza artificiale "
    + "che si occupa di sviluppare algoritmi in grado di apprendere "
    + "automaticamente dai dati. A differenza della programmazione "
    + "tradizionale, dove le regole sono esplicitamente codificate, "
    + "nel machine learning il sistema inferisce pattern e relazioni "
    + "direttamente dagli esempi forniti. "
    + "I principali paradigmi di apprendimento includono: "
    + "apprendimento supervisionato, non supervisionato, "
    + "semi-supervisionato e per rinforzo. "
    + "Le applicazioni spaziano dalla computer vision "
    + "al natural language processing, dalla robotica "
    + "alla bioinformatica. "
    + "Negli ultimi anni, il deep learning ha rivoluzionato "
    + "il campo, permettendo di affrontare problemi "
    + "sempre più complessi con risultati notevoli. "
    + "L'uso di reti neurali profonde, trasformatori "
    + "e modelli generativi ha aperto nuove frontiere "
    + "nella ricerca e nell'industria."
)


# ── Test ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_graph_diamond_completes():
    """Run the full graph end-to-end with all nodes mocked.

    Verifies:
    1. The graph invokes without errors
    2. All expected output keys are present in final state
    3. Progress events trace the correct node order
    4. The diamond pattern fan-out nodes (overview, coherence, citations)
       all ran and produced their expected outputs
    5. The judge approved the final document
    """
    # ── Build initial state ────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []

    async def _record_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "appunti.pdf",
            "full_text": "Testo di esempio sul machine learning. " * 20,
            "mandatory_figures": [],
            "figure_captions": {},
        },
        {
            "filename": "slide.pdf",
            "full_text": "Slide sulle reti neurali. " * 20,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Crea un documento sul machine learning",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_test")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record_progress,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    # ── Mock ALL external dependencies ─────────────────────────────────────
    # The analyse_document mock: returns SourceAnalysis per document.
    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": f"Sintesi di {doc['filename']}",
            "topics": ["machine learning", "AI"],
            "formulas": [],
            "figures": [],
            "keywords": ["ml", "ai"],
            "references": [],
        }

    # plan_document returns (title, plan). Must span 2+ chapters to trigger
    # the overview_node (requires len(chapters) >= 2).
    async def _mock_plan(
        analyses: list,
        user_prompt: str,
        language: str,
        llm_config: dict,
        structure_hint: str,
    ) -> tuple[str, list[dict]]:
        plan = [
            {
                "part_title": "Capitolo 1 - Fondamenti",
                "title": "1.1 Introduzione",
                "order_index": 0,
                "outline": {"punti": ["Definizioni", "Paradigmi"]},
                "source_filenames": ["appunti.pdf"],
            },
            {
                "part_title": "Capitolo 2 - Avanzato",
                "title": "2.1 Deep Learning",
                "order_index": 1,
                "outline": {"punti": ["Reti neurali", "Training"]},
                "source_filenames": ["appunti.pdf", "slide.pdf"],
            },
            {
                "part_title": "Capitolo 2 - Avanzato",
                "title": "2.2 Applicazioni",
                "order_index": 2,
                "outline": {"punti": ["NLP", "Computer Vision"]},
                "source_filenames": ["slide.pdf"],
            },
        ]
        return "Machine Learning: Una Panoramica", plan

    # write_section mock: returns a WrittenSection with long enough content
    # to skip the expansion pass (threshold=600).
    async def _mock_write_section(
        section: dict,
        documents_by_name: dict,
        mandatory_figures: list,
        captions_by_path: dict,
        few_shot: str,
        language: str,
        llm_config: dict,
        available_refs: list | None = None,
        writer_context: list[str] | None = None,
        use_knowledge: bool = False,
        user_sources_context: str = "",
    ) -> dict:
        return {
            "title": section["title"],
            "part_title": section["part_title"],
            "order_index": section["order_index"],
            "latex": f"\\section{{{section['title']}}}\n" + _LONG_LATEX,
            "outline": section.get("outline", {}),
            "source_filenames": section.get("source_filenames", []),
        }

    # summarize_section_context mock: returns a few facts.
    async def _mock_summarize_context(result: dict, llm_config: dict) -> list[str]:
        return [
            f"Fatto estratto da {result['title']}: concetto principale",
            f"Secondo fatto da {result['title']}: applicazione pratica",
        ]

    # call_llm_structured mock for the overview node.
    async def _mock_call_llm_structured(
        llm_config: dict,
        system: str,
        user: str,
        schema: type,
        temperature: float = 0.3,
        label: str = "",
    ) -> _MockOverviewVerdict:
        return _MockOverviewVerdict()

    # check_coherence mock: everything is coherent.
    async def _mock_check_coherence(
        facts: dict,
        llm_config: dict,
    ) -> dict:
        return {
            "approved": True,
            "score": 95,
            "issues": [],
            "summary": "Nessuna incoerenza rilevata",
        }

    # audit_citations mock: all citations are valid.
    async def _mock_audit_citations(
        sections: list,
        references_pool: list,
        user_sources: list | None,
        llm_config: dict,
    ) -> dict:
        return {
            "approved": True,
            "score": 100,
            "uncited_user_sources": [],
            "unknown_citations": [],
            "issues": [],
            "summary": "Tutte le citazioni valide",
        }

    # write_and_compile mock: simulates successful pdflatex.
    def _mock_write_and_compile(
        tex_content: str,
        work_dir: Path,
        figures_src: Path | None = None,
        job_name: str = "main",
        allowed_figures: set[str] | None = None,
        bib_content: str | None = None,
    ) -> _MockCompileResult:
        return _MockCompileResult()

    # judge_structure mock: approves the document.
    async def _mock_judge_structure(
        latex: str,
        llm_config: dict,
        pdf_path: str | None,
        compile_log: str | None,
        use_vision: bool = False,
    ) -> _MockVerdict:
        return _MockVerdict()

    # ── Patch everything ───────────────────────────────────────────────────
    with (
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ) as mock_analyze,
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ) as mock_plan,
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write_section),
        ) as mock_write_section,
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize_context),
        ) as mock_summarize,
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(side_effect=_mock_call_llm_structured),
        ) as mock_overview,
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(side_effect=_mock_check_coherence),
        ) as mock_coherence,
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(side_effect=_mock_audit_citations),
        ) as mock_citations,
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_write_and_compile,
        ) as mock_compile,
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge_structure),
        ) as mock_judge,
        patch(
            "app.agents.graph.lint_latex",
            side_effect=lambda latex: (latex, []),
        ),
    ):
        # ── Run the graph ──────────────────────────────────────────────────
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # ── Assertions: final state keys ───────────────────────────────────────

    # Core pipeline outputs must be present.
    assert "analyses" in final, "analyses key missing from final state"
    assert "plan" in final, "plan key missing from final state"
    assert "sections" in final, "sections key missing from final state"
    assert "title" in final, "title key missing from final state"
    assert "final_latex" in final, "final_latex key missing from final state"
    assert "pdf_path" in final, "pdf_path key missing from final state"
    assert "references_pool" in final, "references_pool key missing from final state"

    # Diamond pattern outputs must be present.
    assert "overview_latex" in final, "overview_latex should be set by overview_node"
    assert "coherence_score" in final, "coherence_score should be set by coherence_node"
    assert "coherence_issues" in final, (
        "coherence_issues should be set by coherence_node"
    )
    assert "citation_report" in final, "citation_report should be set by citation_node"
    assert "citation_issues" in final, "citation_issues should be set by citation_node"

    # Judge must have approved.
    assert "judge_action" in final, "judge_action should be present"
    assert final["judge_action"] == "approve", (
        f"Expected judge_action='approve', got '{final.get('judge_action')}'"
    )
    assert final.get("judge_score") == 92

    # Compilation must have succeeded.
    assert final["pdf_path"] is not None, "Expected a successful PDF output"

    # ── Assertions: call counts ────────────────────────────────────────────
    # 2 documents → 2 analyze_document calls.
    assert mock_analyze.call_count == 2, (
        f"Expected 2 analyze_document calls, got {mock_analyze.call_count}"
    )
    # 1 plan_document call.
    assert mock_plan.call_count == 1, (
        f"Expected 1 plan_document call, got {mock_plan.call_count}"
    )
    # 3 sections → 3 write_section calls.
    assert mock_write_section.call_count == 3, (
        f"Expected 3 write_section calls, got {mock_write_section.call_count}"
    )
    # 3 sections → 3 summarize_section_context calls.
    assert mock_summarize.call_count == 3, (
        f"Expected 3 summarize calls, got {mock_summarize.call_count}"
    )
    # overview_node, coherence_node, citation_node each call LLM once.
    assert mock_overview.call_count == 1, (
        f"Expected 1 overview LLM call, got {mock_overview.call_count}"
    )
    assert mock_coherence.call_count == 1, (
        f"Expected 1 coherence check, got {mock_coherence.call_count}"
    )
    assert mock_citations.call_count == 1, (
        f"Expected 1 citation audit, got {mock_citations.call_count}"
    )
    assert mock_judge.call_count == 1, (
        f"Expected 1 judge_structure call, got {mock_judge.call_count}"
    )
    # First compile attempt succeeds → exactly 1 write_and_compile call.
    assert mock_compile.call_count == 1, (
        f"Expected 1 compilation, got {mock_compile.call_count}"
    )

    # ── Assertions: progress event order ───────────────────────────────────
    stages = [e.get("stage") for e in progress_events if e.get("stage")]
    # The graph must visit these stages.
    expected_order = [
        "analyzing",  # analyze_node start + end
        "analyzing",
        "planning",  # plan_node start + end
        "planning",
        "writing",  # write_node start + per-section updates
        "writing",
        "writing",
        "writing",
        "writing",  # extra for the 3rd section's context extraction message
        "overview",  # overview_node
        "overview",
        "coherence",  # coherence_node
        "citations",  # citation_node
        "merge",  # merge_node
        "reviewing",  # review_node (assemble + compile)
        "reviewing",
        "judging",  # judge_node start + end
        "judging",
    ]

    # Verify all expected stages appear (order may vary for fan-out nodes
    # running in parallel within LangGraph).
    found_stages = set(stages)
    for stage in set(e[0] for e in expected_order if isinstance(e, tuple)):
        assert stage in found_stages, f"Stage '{stage}' not found in progress events"

    # The first event must be analyzing.
    assert stages[0] == "analyzing", (
        f"First stage should be 'analyzing', got '{stages[0]}'"
    )
    # The last few events should include judging.
    last_five = stages[-5:]
    assert "judging" in last_five, (
        f"Last stages should include 'judging', got {last_five}"
    )

    # ── Assertions: diamond parallel results are correct ───────────────────
    assert final["coherence_score"] == 95, (
        f"Expected coherence_score=95, got {final['coherence_score']}"
    )
    assert final["coherence_issues"] == [], (
        f"Expected no coherence issues, got {final['coherence_issues']}"
    )
    assert final["citation_report"] == "Tutte le citazioni valide"
    assert final["citation_issues"] == []

    # overview_latex should contain the panorama chapter.
    assert "Panoramica" in final["overview_latex"], (
        f"overview_latex should contain 'Panoramica', got: {final['overview_latex'][:200]}"
    )


@pytest.mark.asyncio
async def test_full_graph_compile_failure_then_judge_approves():
    """Graph completes even when the first compile fails but review retries succeed.

    Verifies the retry loop in review_node: mock write_and_compile to fail
    once, then succeed, and verify the graph still reaches judge→approve.
    """
    progress_events: list[dict[str, Any]] = []

    async def _record(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "doc.pdf",
            "full_text": "Testo. " * 30,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Test",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_retry")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": "Sintesi",
            "topics": ["test"],
            "formulas": [],
            "figures": [],
            "keywords": [],
            "references": [],
        }

    async def _mock_plan(*args: Any, **kwargs: Any) -> tuple[str, list[dict]]:
        return "Test Doc", [
            {
                "part_title": "Capitolo 1",
                "title": "1.1 Test",
                "order_index": 0,
                "outline": {"punti": ["A"]},
                "source_filenames": ["doc.pdf"],
            }
        ]

    async def _mock_write_section(*args: Any, **kwargs: Any) -> dict:
        return {
            "title": "1.1 Test",
            "part_title": "Capitolo 1",
            "order_index": 0,
            "latex": _LONG_LATEX,
            "outline": {},
            "source_filenames": ["doc.pdf"],
        }

    async def _mock_summarize(*args: Any, **kwargs: Any) -> list[str]:
        return ["Fatto di test"]

    async def _mock_overview(*args: Any, **kwargs: Any) -> _MockOverviewVerdict:
        return _MockOverviewVerdict()

    async def _mock_coherence(*args: Any, **kwargs: Any) -> dict:
        return {"approved": True, "score": 100, "issues": [], "summary": "OK"}

    async def _mock_citations(*args: Any, **kwargs: Any) -> dict:
        return {
            "approved": True,
            "score": 100,
            "uncited_user_sources": [],
            "unknown_citations": [],
            "issues": [],
            "summary": "OK",
        }

    async def _mock_judge(*args: Any, **kwargs: Any) -> _MockVerdict:
        return _MockVerdict()

    # review_document is called when compilation fails (retry path).
    async def _mock_review(latex: str, llm_config: dict, log: str) -> str:
        return latex  # return unchanged (fix was "applied")

    # Compilation: fail once then succeed.
    compile_calls: list[int] = [0]

    def _mock_compile(
        tex_content: str,
        work_dir: Path,
        figures_src: Path | None = None,
        job_name: str = "main",
        allowed_figures: set[str] | None = None,
        bib_content: str | None = None,
    ) -> _MockCompileResult:
        compile_calls[0] += 1
        if compile_calls[0] == 1:
            # First attempt fails.
            return _MockCompileResult(
                success=False,
                pdf_path=None,
                log="! Undefined control sequence.\nl.42 \\badcommand",
            )
        # Second attempt succeeds.
        return _MockCompileResult()

    with (
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ),
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ),
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write_section),
        ),
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize),
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(side_effect=_mock_overview),
        ),
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(side_effect=_mock_coherence),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(side_effect=_mock_citations),
        ),
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ) as mock_compile,
        patch(
            "app.agents.graph.review_document",
            AsyncMock(side_effect=_mock_review),
        ) as mock_reviewer,
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge),
        ),
        patch(
            "app.agents.graph.lint_latex",
            return_value=(_LONG_LATEX, []),
        ),
    ):
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # Verify: two compile attempts, one review_document call (the retry).
    assert mock_compile.call_count == 2, (
        f"Expected 2 compile attempts, got {mock_compile.call_count}"
    )
    assert mock_reviewer.call_count == 1, (
        f"Expected 1 review_document call (retry), got {mock_reviewer.call_count}"
    )

    # Final state must still have a valid PDF (from the second attempt).
    assert final["pdf_path"] is not None, "Expected PDF after retry"
    assert final["judge_action"] == "approve"

    # Progress events must include the retry warning stages.
    stages = [e.get("stage") for e in progress_events if e.get("stage")]
    assert "reviewing" in stages
    # The warning about retry should appear.
    retry_messages = [
        e.get("message", "")
        for e in progress_events
        if "Correzione errori" in e.get("message", "")
    ]
    assert len(retry_messages) >= 1, (
        f"Expected a retry warning message, got none. Messages: "
        f"{[e.get('message') for e in progress_events]}"
    )


@pytest.mark.asyncio
async def test_full_graph_single_source_no_overview():
    """Single source + single chapter → overview_node returns {} (not triggered).

    With only one document and one chapter, the overview threshold is not met
    (``overview_min_chapters`` defaults to 2). Verify overview_latex is NOT in
    the final state.
    """
    progress_events: list[dict[str, Any]] = []

    async def _record(event: dict[str, Any]) -> None:
        progress_events.append(event)

    initial: GraphState = {
        "documents": [
            {
                "filename": "single.pdf",
                "full_text": "Testo singolo documento. " * 20,
                "mandatory_figures": [],
                "figure_captions": {},
            },
        ],
        "user_prompt": "Crea un documento",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_single")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": "Sintesi",
            "topics": ["unico"],
            "formulas": [],
            "figures": [],
            "keywords": [],
            "references": [],
        }

    async def _mock_plan(*args: Any, **kwargs: Any) -> tuple[str, list[dict]]:
        return "Documento Singolo", [
            {
                "part_title": "Capitolo Unico",
                "title": "1.1 Sezione",
                "order_index": 0,
                "outline": {"punti": ["A"]},
                "source_filenames": ["single.pdf"],
            }
        ]

    async def _mock_write(*args: Any, **kwargs: Any) -> dict:
        return {
            "title": "1.1 Sezione",
            "part_title": "Capitolo Unico",
            "order_index": 0,
            "latex": _LONG_LATEX,
            "outline": {},
            "source_filenames": ["single.pdf"],
        }

    async def _mock_summarize(*args: Any, **kwargs: Any) -> list[str]:
        return ["Fatto"]

    async def _mock_coherence(*args: Any, **kwargs: Any) -> dict:
        return {"approved": True, "score": 100, "issues": [], "summary": "OK"}

    async def _mock_citations(*args: Any, **kwargs: Any) -> dict:
        return {
            "approved": True,
            "score": 100,
            "uncited_user_sources": [],
            "unknown_citations": [],
            "issues": [],
            "summary": "OK",
        }

    async def _mock_judge(*args: Any, **kwargs: Any) -> _MockVerdict:
        return _MockVerdict()

    def _mock_compile(*args: Any, **kwargs: Any) -> _MockCompileResult:
        return _MockCompileResult()

    with (
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ),
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ),
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write),
        ),
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize),
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(return_value=_MockOverviewVerdict()),
        ) as mock_overview_llm,
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(side_effect=_mock_coherence),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(side_effect=_mock_citations),
        ),
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ),
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge),
        ),
        patch(
            "app.agents.graph.lint_latex",
            return_value=(_LONG_LATEX, []),
        ),
    ):
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # overview_node should have returned {} → no overview_latex in final state.
    assert "overview_latex" not in final or final.get("overview_latex") is None, (
        "overview_latex should NOT be present for single-source single-chapter docs"
    )

    # The overview LLM should never have been called.
    assert mock_overview_llm.call_count == 0, (
        f"overview LLM should not be called for single-chapter doc, "
        f"got {mock_overview_llm.call_count} calls"
    )

    # The rest of the pipeline still completed successfully.
    assert final.get("judge_action") == "approve"
    assert final["pdf_path"] is not None


# ── User sources E2E test ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_graph_user_sources_merged_and_audited():
    r"""User sources are merged into references_pool and audited by citations.

    Verifies the full flow:
    1. ``user_sources`` from initial state are merged into ``references_pool``
       by ``write_node`` (with ``source_filename="__user__"``).
    2. ``audit_citations`` is called with the user_sources and detects that
       they are NOT cited (our mocked sections have no \cite).
    3. ``citation_issues`` in final state reflect the uncited sources.
    4. The merge progress event mentions the number of merged sources.
    """
    from app.services.bibliography import make_key

    # ── Compute expected keys ──────────────────────────────────────────────
    user_sources = [
        {
            "authors": "He",
            "title": "Deep Residual Learning",
            "year": "2016",
            "venue": "CVPR",
        },
        {
            "authors": "Vaswani",
            "title": "Attention Is All You Need",
            "year": "2017",
            "venue": "NIPS",
        },
    ]
    _used: set[str] = set()
    expected_keys: list[str] = []
    for us in user_sources:
        key = make_key(us, _used)
        _used.add(key)
        expected_keys.append(key)

    # ── Build initial state ────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []

    async def _record_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "paper.pdf",
            "full_text": "Testo di esempio sul deep learning. " * 20,
            "mandatory_figures": [],
            "figure_captions": {},
        },
        {
            "filename": "notes.pdf",
            "full_text": "Note sui trasformatori e attention. " * 20,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Crea un documento su deep learning e transformers",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_usersrc")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record_progress,
        "writer_use_knowledge": False,
        "user_sources": list(user_sources),
    }

    # ── Mocks ──────────────────────────────────────────────────────────────
    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": f"Sintesi di {doc['filename']}",
            "topics": ["deep learning", "transformers"],
            "formulas": [],
            "figures": [],
            "keywords": ["dl", "nlp"],
            "references": [],
        }

    async def _mock_plan(
        analyses: list,
        user_prompt: str,
        language: str,
        llm_config: dict,
        structure_hint: str,
    ) -> tuple[str, list[dict]]:
        plan = [
            {
                "part_title": "Capitolo 1 - Deep Learning",
                "title": "1.1 Reti Residuali",
                "order_index": 0,
                "outline": {"punti": ["Deep residual learning", "Skip connections"]},
                "source_filenames": ["paper.pdf"],
            },
            {
                "part_title": "Capitolo 2 - Transformers",
                "title": "2.1 Meccanismo di Attention",
                "order_index": 1,
                "outline": {"punti": ["Self-attention", "Multi-head"]},
                "source_filenames": ["notes.pdf"],
            },
        ]
        return "Deep Learning e Transformers", plan

    # write_section mock: returns LaTeX WITHOUT \cite commands, so the
    # citation auditor will detect user sources as uncited.
    async def _mock_write_section(
        section: dict,
        documents_by_name: dict,
        mandatory_figures: list,
        captions_by_path: dict,
        few_shot: str,
        language: str,
        llm_config: dict,
        available_refs: list | None = None,
        writer_context: list[str] | None = None,
        use_knowledge: bool = False,
        user_sources_context: str = "",
    ) -> dict:
        return {
            "title": section["title"],
            "part_title": section["part_title"],
            "order_index": section["order_index"],
            "latex": f"\\section{{{section['title']}}}\n" + _LONG_LATEX,
            "outline": section.get("outline", {}),
            "source_filenames": section.get("source_filenames", []),
        }

    async def _mock_summarize_context(result: dict, llm_config: dict) -> list[str]:
        return [f"Fatto da {result['title']}"]

    async def _mock_overview(
        llm_config: dict,
        system: str,
        user: str,
        schema: type,
        temperature: float = 0.3,
        label: str = "",
    ) -> _MockOverviewVerdict:
        return _MockOverviewVerdict()

    async def _mock_coherence(facts: dict, llm_config: dict) -> dict:
        return {"approved": True, "score": 95, "issues": [], "summary": "OK"}

    # Citation audit mock: detects the user sources as uncited.
    async def _mock_audit_citations(
        sections: list,
        references_pool: list,
        user_sources: list | None,
        llm_config: dict,
    ) -> dict:
        return {
            "approved": False,
            "score": 70,
            "uncited_user_sources": list(expected_keys),
            "unknown_citations": [],
            "issues": [f"Fonte utente non citata: {k}" for k in expected_keys],
            "summary": f"{len(expected_keys)} fonti utente non citate",
        }

    async def _mock_judge(
        latex: str,
        llm_config: dict,
        pdf_path: str | None,
        compile_log: str | None,
        use_vision: bool = False,
    ) -> _MockVerdict:
        return _MockVerdict()

    def _mock_compile(
        tex_content: str,
        work_dir: Path,
        figures_src: Path | None = None,
        job_name: str = "main",
        allowed_figures: set[str] | None = None,
        bib_content: str | None = None,
    ) -> _MockCompileResult:
        return _MockCompileResult()

    # ── Patch and run ──────────────────────────────────────────────────────
    with (
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ),
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ),
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write_section),
        ),
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize_context),
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(side_effect=_mock_overview),
        ),
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(side_effect=_mock_coherence),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(side_effect=_mock_audit_citations),
        ) as mock_citations,
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ),
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge),
        ),
        patch(
            "app.agents.graph.lint_latex",
            side_effect=lambda latex: (latex, []),
        ),
    ):
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # ── Assertions: user sources merged into references_pool ───────────────
    pool = final.get("references_pool", [])
    assert pool, "references_pool should not be empty"

    # Find user-source entries (identified by source_filename="__user__").
    user_pool_entries = [r for r in pool if r.get("source_filename") == "__user__"]
    assert len(user_pool_entries) == len(user_sources), (
        f"Expected {len(user_sources)} user entries in pool, "
        f"found {len(user_pool_entries)}. Pool: {pool}"
    )

    # Each expected key must appear in the pool.
    pool_keys = {r.get("key") for r in pool}
    for key in expected_keys:
        assert key in pool_keys, (
            f"Expected key '{key}' from user source in references_pool. "
            f"Pool keys: {sorted(pool_keys)}"
        )

    # Each user pool entry must have the correct metadata.
    for entry in user_pool_entries:
        assert entry["source_filename"] == "__user__"
        assert entry.get("authors") or entry.get("title"), (
            f"User pool entry missing authors/title: {entry}"
        )

    # ── Assertions: citation auditor was called with user_sources ──────────
    assert mock_citations.call_count == 1
    # audit_citations is called with keyword args in the graph.
    passed_user_sources = mock_citations.call_args[1].get("user_sources")
    assert passed_user_sources is not None, (
        "audit_citations must be called with user_sources"
    )
    assert len(passed_user_sources) == len(user_sources), (
        f"Expected {len(user_sources)} user_sources passed to audit_citations, "
        f"got {len(passed_user_sources)}"
    )

    # ── Assertions: citation issues in final state ─────────────────────────
    assert final.get("citation_issues"), (
        "citation_issues should report uncited user sources"
    )
    assert len(final["citation_issues"]) == len(expected_keys), (
        f"Expected {len(expected_keys)} citation issues, "
        f"got {len(final['citation_issues'])}"
    )
    # Each expected key should be mentioned in the issues.
    for key in expected_keys:
        found = any(key in issue for issue in final["citation_issues"])
        assert found, (
            f"Citation issue for key '{key}' not found in {final['citation_issues']}"
        )

    assert (
        final.get("citation_report") == f"{len(expected_keys)} fonti utente non citate"
    )

    # ── Assertions: merge progress mentions citation problems ──────────────
    # There are two "merge" stage events: merge_analyses_node (first) and
    # merge_node (diamond fan-in, second). We want the latter.
    merge_events = [e for e in progress_events if e.get("stage") == "merge"]
    assert merge_events, "Merge progress event should exist"
    merge_msg = merge_events[-1].get("message", "")
    assert "problemi citazioni" in merge_msg, (
        f"Merge should report citation issues. Got: {merge_msg}"
    )

    # ── Assertions: the rest of the pipeline still completed ───────────────
    assert final.get("judge_action") == "approve"
    assert final["pdf_path"] is not None


# ── Judge revision loop E2E test ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_graph_judge_disapproves_then_approves_on_revision():
    """Judge disapproves the first pass, a revision is made, then approved.

    Verifies the full judge → revise → review → judge loop:
    1. First judge call returns ``approved=False`` with structural issues.
    2. ``revise_structure`` produces a corrected LaTeX document.
    3. ``review_node`` recompiles the revised document.
    4. Second judge call approves the corrected version.
    5. The graph terminates with ``judge_action="approve"``.
    """
    from app.core.config import settings as _cfg

    # ── Build initial state ────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []

    async def _record_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "doc.pdf",
            "full_text": "Testo di esempio. " * 20,
            "mandatory_figures": [],
            "figure_captions": {},
        },
        {
            "filename": "notes.pdf",
            "full_text": "Note aggiuntive. " * 20,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Crea un documento",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_judge_rev")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record_progress,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    # ── Mocks ──────────────────────────────────────────────────────────────
    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": f"Sintesi di {doc['filename']}",
            "topics": ["topic"],
            "formulas": [],
            "figures": [],
            "keywords": [],
            "references": [],
        }

    async def _mock_plan(*args: Any, **kwargs: Any) -> tuple[str, list[dict]]:
        plan = [
            {
                "part_title": "Capitolo 1",
                "title": "1.1 Intro",
                "order_index": 0,
                "outline": {"punti": ["A"]},
                "source_filenames": ["doc.pdf"],
            },
            {
                "part_title": "Capitolo 2",
                "title": "2.1 Avanzato",
                "order_index": 1,
                "outline": {"punti": ["B"]},
                "source_filenames": ["notes.pdf"],
            },
        ]
        return "Documento Test", plan

    async def _mock_write_section(*args: Any, **kwargs: Any) -> dict:
        return {
            "title": "Sezione",
            "part_title": "Capitolo",
            "order_index": 0,
            "latex": _LONG_LATEX,
            "outline": {},
            "source_filenames": ["doc.pdf"],
        }

    async def _mock_summarize(*args: Any, **kwargs: Any) -> list[str]:
        return ["Fatto"]

    async def _mock_overview(*args: Any, **kwargs: Any) -> _MockOverviewVerdict:
        return _MockOverviewVerdict()

    async def _mock_coherence(*args: Any, **kwargs: Any) -> dict:
        return {"approved": True, "score": 95, "issues": [], "summary": "OK"}

    async def _mock_citations(*args: Any, **kwargs: Any) -> dict:
        return {
            "approved": True,
            "score": 100,
            "uncited_user_sources": [],
            "unknown_citations": [],
            "issues": [],
            "summary": "OK",
        }

    # Judge: first call disapproves, second approves.
    _judge_verdicts = [
        type(
            "V",
            (),
            {
                "approved": False,
                "score": 35,
                "issues": ["Manca una conclusione", "Capitoli sbilanciati"],
                "summary": "Struttura da rivedere",
            },
        )(),
        type(
            "V",
            (),
            {
                "approved": True,
                "score": 88,
                "issues": [],
                "summary": "Struttura migliorata, approvata",
            },
        )(),
    ]

    async def _mock_judge_structure(
        latex: str,
        llm_config: dict,
        pdf_path: str | None,
        compile_log: str | None,
        use_vision: bool = False,
    ):
        return _judge_verdicts.pop(0)

    # revise_structure mock: returns a "corrected" LaTeX document.
    _REVISED_LATEX = (
        r"\documentclass{report}\begin{document}"
        r"\chapter{Introduzione}\section{Intro}Contenuto migliorato."
        r"\chapter{Conclusione}\section{Fine}Documento corretto."
        r"\end{document}"
    )

    async def _mock_revise_structure(
        latex: str,
        issues: list[str],
        llm_config: dict,
    ) -> str:
        return _REVISED_LATEX

    def _mock_compile(
        tex_content: str,
        work_dir: Path,
        figures_src: Path | None = None,
        job_name: str = "main",
        allowed_figures: set[str] | None = None,
        bib_content: str | None = None,
    ) -> _MockCompileResult:
        return _MockCompileResult()

    # ── Patch and run ──────────────────────────────────────────────────────
    with (
        patch.object(_cfg, "judge_max_iterations", 2),
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ),
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ),
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write_section),
        ),
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize),
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(side_effect=_mock_overview),
        ),
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(side_effect=_mock_coherence),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(side_effect=_mock_citations),
        ),
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge_structure),
        ) as mock_judge,
        patch(
            "app.agents.graph.revise_structure",
            AsyncMock(side_effect=_mock_revise_structure),
        ) as mock_revise,
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ) as mock_compile,
        patch(
            "app.agents.graph.lint_latex",
            side_effect=lambda latex: (latex, []),
        ),
    ):
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # ── Assertions: judge ran twice ───────────────────────────────────────
    assert mock_judge.call_count == 2, (
        f"Expected 2 judge_structure calls (disapprove + approve), "
        f"got {mock_judge.call_count}"
    )
    # Second judge call should receive the revised LaTeX (not the original).
    second_call_latex = mock_judge.call_args_list[1][0][0]
    assert "Contenuto migliorato" in second_call_latex, (
        "Second judge call should inspect the revised LaTeX"
    )

    # ── Assertions: revise_structure called once ──────────────────────────
    assert mock_revise.call_count == 1, (
        f"Expected 1 revise_structure call, got {mock_revise.call_count}"
    )
    # revise_structure receives (latex, issues, llm_config) as positional args.
    issues_passed = mock_revise.call_args[0][1]
    assert "Manca una conclusione" in issues_passed, (
        f"revise_structure should receive judge issues. Got: {issues_passed}"
    )

    # ── Assertions: two compilations (initial + revision recompile) ────────
    assert mock_compile.call_count == 2, (
        f"Expected 2 compilations (initial + revision), got {mock_compile.call_count}"
    )

    # ── Assertions: final state ────────────────────────────────────────────
    assert final.get("judge_action") == "approve", (
        f"Expected final judge_action='approve', got '{final.get('judge_action')}'"
    )
    assert final.get("judge_score") == 88, (
        f"Expected final judge_score=88, got {final.get('judge_score')}"
    )
    assert final.get("judge_rounds") == 1, (
        f"Expected judge_rounds=1 (one revision round), got {final.get('judge_rounds')}"
    )
    assert final["pdf_path"] is not None

    # ── Assertions: progress events trace the full loop ────────────────────

    # Should have two judging blocks.
    judging_events = [e for e in progress_events if e.get("stage") == "judging"]
    assert len(judging_events) >= 3, (
        f"Expected at least 3 judging events (disapprove start+end + approve start+end), "
        f"got {len(judging_events)}: {judging_events}"
    )

    # Should have the revision warning.
    revision_warnings = [
        e for e in progress_events if "Revisione struttura" in e.get("message", "")
    ]
    assert len(revision_warnings) >= 1, (
        f"Expected 'Revisione struttura' progress event. "
        f"Messages: {[e.get('message') for e in progress_events]}"
    )

    # Should have the recompilation-after-revision progress event.
    ricompilazione = [
        e for e in progress_events if "Ricompilazione" in e.get("message", "")
    ]
    assert len(ricompilazione) >= 1, (
        f"Expected 'Ricompilazione dopo revisione' progress event. "
        f"Got: {[e.get('message') for e in progress_events if 'Ricompil' in e.get('message', '')]}"
    )

    # The final judging message should indicate approval.
    approval_msgs = [
        e
        for e in progress_events
        if e.get("stage") == "judging" and "approvata" in e.get("message", "")
    ]
    assert len(approval_msgs) >= 1, (
        f"Expected at least one 'Struttura approvata' message. "
        f"Judging msgs: {[e.get('message') for e in judging_events]}"
    )


# ── Judge revision compile failure → rollback E2E test ───────────────────


@pytest.mark.asyncio
async def test_full_graph_judge_revision_fails_rollback_to_good():
    """Judge revision doesn't compile → rollback to the previous good version.

    Flow:
    1. Initial compile succeeds → ``good_latex`` / ``good_pdf`` saved.
    2. Judge disapproves → ``revise_structure`` produces broken LaTeX.
    3. ``review_node`` in revision mode: all compile attempts fail.
    4. Rollback: returns ``good_latex`` / ``good_pdf`` instead of the broken
       revision.  Progress event: "Revisione strutturale scartata".
    """
    from app.core.config import settings as _cfg

    # ── Build initial state ────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []

    async def _record_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "doc.pdf",
            "full_text": "Testo. " * 15,
            "mandatory_figures": [],
            "figure_captions": {},
        },
        {
            "filename": "notes.pdf",
            "full_text": "Note. " * 15,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Crea un documento",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_rollback")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record_progress,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    # ── Mocks ──────────────────────────────────────────────────────────────
    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": "Sintesi",
            "topics": ["topic"],
            "formulas": [],
            "figures": [],
            "keywords": [],
            "references": [],
        }

    async def _mock_plan(*args: Any, **kwargs: Any) -> tuple[str, list[dict]]:
        plan = [
            {
                "part_title": "Capitolo 1",
                "title": "1.1 Intro",
                "order_index": 0,
                "outline": {"punti": ["A"]},
                "source_filenames": ["doc.pdf"],
            },
            {
                "part_title": "Capitolo 2",
                "title": "2.1 Topic",
                "order_index": 1,
                "outline": {"punti": ["B"]},
                "source_filenames": ["notes.pdf"],
            },
        ]
        return "Doc", plan

    async def _mock_write_section(*args: Any, **kwargs: Any) -> dict:
        return {
            "title": "S",
            "part_title": "C",
            "order_index": 0,
            "latex": _LONG_LATEX,
            "outline": {},
            "source_filenames": ["doc.pdf"],
        }

    async def _mock_summarize(*args: Any, **kwargs: Any) -> list[str]:
        return ["Fatto"]

    async def _mock_overview(*args: Any, **kwargs: Any) -> _MockOverviewVerdict:
        return _MockOverviewVerdict()

    async def _mock_coherence(*args: Any, **kwargs: Any) -> dict:
        return {"approved": True, "score": 95, "issues": [], "summary": "OK"}

    async def _mock_citations(*args: Any, **kwargs: Any) -> dict:
        return {
            "approved": True,
            "score": 100,
            "uncited_user_sources": [],
            "unknown_citations": [],
            "issues": [],
            "summary": "OK",
        }

    # Judge: disapproves.
    _disapprove = type(
        "V",
        (),
        {
            "approved": False,
            "score": 25,
            "issues": ["Struttura inadeguata"],
            "summary": "Da rifare",
        },
    )()

    async def _mock_judge_structure(
        latex: str,
        llm_config: dict,
        pdf_path: str | None,
        compile_log: str | None,
        use_vision: bool = False,
    ):
        return _disapprove

    # revise_structure returns "broken" LaTeX that won't compile.
    _BROKEN_LATEX = (
        r"\documentclass{report}\begin{document}"
        r"\chapter{Broken}\badcommand"
        r"\end{document}"
    )

    async def _mock_revise_structure(
        latex: str,
        issues: list[str],
        llm_config: dict,
    ) -> str:
        return _BROKEN_LATEX

    # review_document is called during the retry loop when compilation fails.
    async def _mock_review_document(
        latex: str,
        llm_config: dict,
        log: str,
    ) -> str:
        return _BROKEN_LATEX  # "fix" still broken

    # Compilation: first call succeeds (initial), ALL subsequent calls fail.
    compile_calls: list[int] = [0]

    def _mock_compile(
        tex_content: str,
        work_dir: Path,
        figures_src: Path | None = None,
        job_name: str = "main",
        allowed_figures: set[str] | None = None,
        bib_content: str | None = None,
    ) -> _MockCompileResult:
        compile_calls[0] += 1
        if compile_calls[0] == 1:
            # Initial compile succeeds.
            return _MockCompileResult(
                success=True,
                pdf_path="/tmp/output/main.pdf",
                log="Output written on main.pdf (1 page).",
            )
        # All revision attempts fail.
        return _MockCompileResult(
            success=False,
            pdf_path=None,
            log="! Undefined control sequence.\nl.42 \\badcommand",
        )

    # ── Patch and run ──────────────────────────────────────────────────────
    with (
        patch.object(_cfg, "judge_max_iterations", 1),
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ),
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ),
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write_section),
        ),
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize),
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(side_effect=_mock_overview),
        ),
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(side_effect=_mock_coherence),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(side_effect=_mock_citations),
        ),
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge_structure),
        ) as mock_judge,
        patch(
            "app.agents.graph.revise_structure",
            AsyncMock(side_effect=_mock_revise_structure),
        ) as mock_revise,
        patch(
            "app.agents.graph.review_document",
            AsyncMock(side_effect=_mock_review_document),
        ) as mock_reviewer,
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ) as mock_compile,
        patch(
            "app.agents.graph.lint_latex",
            side_effect=lambda latex: (latex, []),
        ),
    ):
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # ── Assertions: judge called once, revision attempted ─────────────────
    assert mock_judge.call_count == 1
    assert mock_revise.call_count == 1
    # review_document called twice during retry loop (MAX_REVIEW_RETRIES=2):
    # attempt 0 fails → review_document → attempt 1 fails → review_document →
    # attempt 2 fails without fix call.
    assert mock_reviewer.call_count == 2, (
        f"Expected 2 review_document calls during retry loop, "
        f"got {mock_reviewer.call_count}"
    )
    # 1 (initial success) + 3 (revision failure attempts 0/1/2) = 4.
    assert mock_compile.call_count == 4, (
        f"Expected 4 compilation attempts (1 initial + 3 revision failures), "
        f"got {mock_compile.call_count}"
    )

    # ── Assertions: rollback occurred ─────────────────────────────────────
    # final_latex should be the ORIGINAL good version (from assemble_document),
    # NOT the broken revised version.
    assert "\\badcommand" not in final.get("final_latex", ""), (
        "final_latex should NOT contain the broken revision command"
    )
    assert final["pdf_path"] is not None, "PDF should exist (rollback to good version)"
    assert final["pdf_path"] == _MockCompileResult.pdf_path, (
        f"PDF path should be from the good compile, got {final['pdf_path']}"
    )

    # judge_action: disapproved (never approved).
    assert final.get("judge_action") == "revise", (
        f"Expected judge_action='revise', got '{final.get('judge_action')}'"
    )

    # ── Assertions: progress events ───────────────────────────────────────
    # Should contain the rollback warning.
    rollback_msgs = [
        e
        for e in progress_events
        if "Revisione strutturale scartata" in e.get("message", "")
    ]
    assert len(rollback_msgs) >= 1, (
        f"Expected 'Revisione strutturale scartata' progress event. "
        f"Got: {[e.get('message') for e in progress_events if 'scartata' in e.get('message', '')]}"
    )

    # Should contain the retry warning messages.
    retry_msgs = [
        e for e in progress_events if "Correzione errori" in e.get("message", "")
    ]
    assert len(retry_msgs) >= 1, (
        f"Expected 'Correzione errori (tentativo ...)' progress events. "
        f"Got: {[e.get('message') for e in progress_events if 'Correzione' in e.get('message', '')]}"
    )

    # Should NOT contain an approval message.
    approval_msgs = [
        e
        for e in progress_events
        if "approvata" in e.get("message", "") and e.get("stage") == "judging"
    ]
    assert not approval_msgs, (
        f"Expected NO approval message. Got: {[e.get('message') for e in approval_msgs]}"
    )


# ── Judge max iterations exhausted E2E test ───────────────────────────────


@pytest.mark.asyncio
async def test_full_graph_judge_max_iterations_exhausted():
    """Judge disapproves TWICE consecutively; graph terminates at max iterations.

    With ``judge_max_iterations=2`` and a judge that never approves:
    1. Round 0: judge disapproves → revise → recompile.
    2. Round 1: ``_after_review`` returns "judge" (round 1 < max 2).
    3. Round 1: judge disapproves AGAIN → revise → recompile.
    4. ``_after_review`` returns ``END`` (round 2 >= max 2).
    5. Graph terminates with ``judge_action="revise"`` (never approved).
    """
    from app.core.config import settings as _cfg

    # ── Build initial state ────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []

    async def _record_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "doc.pdf",
            "full_text": "Testo. " * 15,
            "mandatory_figures": [],
            "figure_captions": {},
        },
        {
            "filename": "notes.pdf",
            "full_text": "Note. " * 15,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Crea un documento",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_judgemax")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record_progress,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    # ── Mocks ──────────────────────────────────────────────────────────────
    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": "Sintesi",
            "topics": ["topic"],
            "formulas": [],
            "figures": [],
            "keywords": [],
            "references": [],
        }

    async def _mock_plan(*args: Any, **kwargs: Any) -> tuple[str, list[dict]]:
        plan = [
            {
                "part_title": "Capitolo 1",
                "title": "1.1 Intro",
                "order_index": 0,
                "outline": {"punti": ["A"]},
                "source_filenames": ["doc.pdf"],
            },
            {
                "part_title": "Capitolo 2",
                "title": "2.1 Topic",
                "order_index": 1,
                "outline": {"punti": ["B"]},
                "source_filenames": ["notes.pdf"],
            },
        ]
        return "Doc", plan

    async def _mock_write_section(*args: Any, **kwargs: Any) -> dict:
        return {
            "title": "S",
            "part_title": "C",
            "order_index": 0,
            "latex": _LONG_LATEX,
            "outline": {},
            "source_filenames": ["doc.pdf"],
        }

    async def _mock_summarize(*args: Any, **kwargs: Any) -> list[str]:
        return ["Fatto"]

    async def _mock_overview(*args: Any, **kwargs: Any) -> _MockOverviewVerdict:
        return _MockOverviewVerdict()

    async def _mock_coherence(*args: Any, **kwargs: Any) -> dict:
        return {"approved": True, "score": 95, "issues": [], "summary": "OK"}

    async def _mock_citations(*args: Any, **kwargs: Any) -> dict:
        return {
            "approved": True,
            "score": 100,
            "uncited_user_sources": [],
            "unknown_citations": [],
            "issues": [],
            "summary": "OK",
        }

    # Judge: ALWAYS disapproves (never approves).
    _always_disapprove = type(
        "V",
        (),
        {
            "approved": False,
            "score": 30,
            "issues": ["Manca introduzione", "Sezioni sbilanciate"],
            "summary": "Struttura inadeguata",
        },
    )()

    async def _mock_judge_structure(
        latex: str,
        llm_config: dict,
        pdf_path: str | None,
        compile_log: str | None,
        use_vision: bool = False,
    ):
        return _always_disapprove

    _REVISED_LATEX = (
        r"\documentclass{report}\begin{document}"
        r"\chapter{Intro}Revised content."
        r"\end{document}"
    )

    async def _mock_revise_structure(
        latex: str,
        issues: list[str],
        llm_config: dict,
    ) -> str:
        return _REVISED_LATEX

    def _mock_compile(
        tex_content: str,
        work_dir: Path,
        figures_src: Path | None = None,
        job_name: str = "main",
        allowed_figures: set[str] | None = None,
        bib_content: str | None = None,
    ) -> _MockCompileResult:
        return _MockCompileResult()

    # ── Patch and run with judge_max_iterations=2 (allows two rounds) ──────
    with (
        patch.object(_cfg, "judge_max_iterations", 2),
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ),
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ),
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write_section),
        ),
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize),
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(side_effect=_mock_overview),
        ),
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(side_effect=_mock_coherence),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(side_effect=_mock_citations),
        ),
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge_structure),
        ) as mock_judge,
        patch(
            "app.agents.graph.revise_structure",
            AsyncMock(side_effect=_mock_revise_structure),
        ) as mock_revise,
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ) as mock_compile,
        patch(
            "app.agents.graph.lint_latex",
            side_effect=lambda latex: (latex, []),
        ),
    ):
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # ── Assertions: judge called twice (two consecutive disapprovals) ──────
    assert mock_judge.call_count == 2, (
        f"Expected 2 judge calls (two disapprovals before max iterations), "
        f"got {mock_judge.call_count}"
    )
    # revise_structure called twice.
    assert mock_revise.call_count == 2, (
        f"Expected 2 revise_structure calls, got {mock_revise.call_count}"
    )
    # Three compilations: initial + revision recompile + second revision recompile.
    assert mock_compile.call_count == 3, (
        f"Expected 3 compilations, got {mock_compile.call_count}"
    )

    # ── Assertions: graph terminated at max iterations ────────────────────
    assert final.get("judge_action") == "revise", (
        f"Expected judge_action='revise' (never approved), "
        f"got '{final.get('judge_action')}'"
    )
    assert final.get("judge_score") == 30, (
        f"Expected judge_score=30 from disapproved verdict, "
        f"got {final.get('judge_score')}"
    )
    assert final.get("judge_rounds") == 2, (
        f"Expected judge_rounds=2 (two revision rounds), got {final.get('judge_rounds')}"
    )
    # The final PDF still exists (from the revision recompile).
    assert final["pdf_path"] is not None, (
        "PDF should exist from revision recompile even though judge disapproved"
    )

    # ── Assertions: progress events ───────────────────────────────────────
    judging_events = [e for e in progress_events if e.get("stage") == "judging"]
    # Should have at least 2 judging events: "Il giudice esamina" + revision warning.
    assert len(judging_events) >= 2, (
        f"Expected at least 2 judging progress events, got {len(judging_events)}"
    )
    # Should contain the revision warning (not approval).
    revision_msgs = [
        e for e in progress_events if "Revisione struttura" in e.get("message", "")
    ]
    assert len(revision_msgs) >= 1, (
        f"Expected 'Revisione struttura' progress event. Got: "
        f"{[e.get('message') for e in progress_events if 'Revisione' in e.get('message', '')]}"
    )
    # The recompilation-after-revision progress event should exist.
    ricompilazione = [
        e for e in progress_events if "Ricompilazione" in e.get("message", "")
    ]
    assert len(ricompilazione) >= 1, "Expected 'Ricompilazione' progress event"
    # Should NOT contain an approval message.
    approval_msgs = [
        e
        for e in progress_events
        if e.get("stage") == "judging" and "approvata" in e.get("message", "")
    ]
    assert not approval_msgs, (
        f"Expected NO approval message (judge never approved). "
        f"Got: {[e.get('message') for e in approval_msgs]}"
    )


# ── Disabled coherence + citations E2E test ───────────────────────────────


@pytest.mark.asyncio
async def test_full_graph_coherence_and_citations_disabled():
    """Both coherence and citations disabled → nodes return {}, graph completes.

    Verifies that when ``coherence_enabled=False`` and ``citations_enabled=False``:
    1. ``check_coherence`` and ``audit_citations`` are NEVER called.
    2. No progress events emitted from coherence or citation nodes.
    3. No coherence_score, coherence_issues, citation_issues, citation_report
       keys appear in final state.
    4. The merge progress event simply says "Verifiche completate".
    5. The graph still completes with judge_action="approve".
    """
    from app.core.config import settings as _cfg

    # ── Build initial state ────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []

    async def _record_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "doc.pdf",
            "full_text": "Testo di esempio. " * 15,
            "mandatory_figures": [],
            "figure_captions": {},
        },
        {
            "filename": "notes.pdf",
            "full_text": "Note aggiuntive. " * 15,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Crea un documento",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_disabled")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record_progress,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    # ── Mocks (same as diamond_completes) ──────────────────────────────────
    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": "Sintesi",
            "topics": ["topic"],
            "formulas": [],
            "figures": [],
            "keywords": [],
            "references": [],
        }

    async def _mock_plan(*args: Any, **kwargs: Any) -> tuple[str, list[dict]]:
        plan = [
            {
                "part_title": "Capitolo 1",
                "title": "1.1 Intro",
                "order_index": 0,
                "outline": {"punti": ["A"]},
                "source_filenames": ["doc.pdf"],
            },
            {
                "part_title": "Capitolo 2",
                "title": "2.1 Topic",
                "order_index": 1,
                "outline": {"punti": ["B"]},
                "source_filenames": ["notes.pdf"],
            },
        ]
        return "Doc", plan

    async def _mock_write_section(*args: Any, **kwargs: Any) -> dict:
        return {
            "title": "S",
            "part_title": "C",
            "order_index": 0,
            "latex": _LONG_LATEX,
            "outline": {},
            "source_filenames": ["doc.pdf"],
        }

    async def _mock_summarize(*args: Any, **kwargs: Any) -> list[str]:
        return ["Fatto"]

    async def _mock_overview(*args: Any, **kwargs: Any) -> _MockOverviewVerdict:
        return _MockOverviewVerdict()

    async def _mock_judge(*args: Any, **kwargs: Any) -> _MockVerdict:
        return _MockVerdict()

    def _mock_compile(*args: Any, **kwargs: Any) -> _MockCompileResult:
        return _MockCompileResult()

    # ── Patch and run with both settings disabled ──────────────────────────
    with (
        patch.object(_cfg, "coherence_enabled", False),
        patch.object(_cfg, "citations_enabled", False),
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ),
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ),
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write_section),
        ),
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize),
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(side_effect=_mock_overview),
        ),
        patch(
            "app.agents.graph.check_coherence",
        ) as mock_coherence,
        patch(
            "app.agents.graph.audit_citations",
        ) as mock_citations,
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ),
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge),
        ),
        patch(
            "app.agents.graph.lint_latex",
            side_effect=lambda latex: (latex, []),
        ),
    ):
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # ── Assertions: LLM functions NEVER called ────────────────────────────
    mock_coherence.assert_not_called()
    mock_citations.assert_not_called()

    # ── Assertions: no coherence/citation keys in final state ─────────────
    assert "coherence_score" not in final, (
        f"coherence_score should not be in final state when disabled: {final.get('coherence_score')}"
    )
    assert "coherence_issues" not in final, (
        "coherence_issues should not be in final state when disabled"
    )
    assert "citation_issues" not in final, (
        "citation_issues should not be in final state when disabled"
    )
    assert "citation_report" not in final, (
        "citation_report should not be in final state when disabled"
    )

    # ── Assertions: no coherence/citation progress events ─────────────────
    coherence_events = [e for e in progress_events if e.get("stage") == "coherence"]
    assert not coherence_events, (
        f"No coherence progress events expected when disabled, got {coherence_events}"
    )
    citation_events = [e for e in progress_events if e.get("stage") == "citations"]
    assert not citation_events, (
        f"No citation progress events expected when disabled, got {citation_events}"
    )

    # ── Assertions: merge just says "Verifiche completate" ────────────────
    # There are two "merge" stage events: merge_analyses_node (first) and
    # merge_node (diamond fan-in, second). We want the latter.
    merge_events = [e for e in progress_events if e.get("stage") == "merge"]
    assert merge_events, "Merge progress event should exist"
    merge_msg = merge_events[-1].get("message", "")
    assert merge_msg == "Verifiche completate", (
        f"Merge should report 'Verifiche completate' with no issues. Got: {merge_msg}"
    )

    # ── Assertions: graph completed successfully ──────────────────────────
    assert final.get("judge_action") == "approve", (
        f"Expected judge_action='approve', got '{final.get('judge_action')}'"
    )
    assert final["pdf_path"] is not None

    # ── Assertions: required stages are still present ──────────────────────
    stages = [e.get("stage") for e in progress_events if e.get("stage")]
    required = {"analyzing", "planning", "writing", "merge", "reviewing", "judging"}
    missing = required - set(stages)
    assert not missing, f"Missing progress stages: {missing}"


# ── Disabled judge E2E test ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_graph_judge_disabled_terminates_after_review():
    """Judge disabled → graph terminates right after review, no judge calls.

    Verifies that when ``judge_enabled=False``:
    1. ``judge_structure`` is NEVER called (not even imported by the graph).
    2. No ``judge_action``, ``judge_score``, or ``judge_rounds`` keys appear
       in the final state.
    3. No judging progress events are emitted.
    4. The graph still completes: PDF produced, all core stages present.
    """
    from app.core.config import settings as _cfg

    # ── Build initial state ────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []

    async def _record_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "doc.pdf",
            "full_text": "Testo di esempio. " * 15,
            "mandatory_figures": [],
            "figure_captions": {},
        },
        {
            "filename": "notes.pdf",
            "full_text": "Note aggiuntive. " * 15,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Crea un documento",
        "language": "italian",
        "llm_config": {"provider": "fake", "model": "test"},
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_nojudge")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record_progress,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    # ── Mocks (same compact style as other disabled tests) ─────────────────
    async def _mock_analyze(doc: dict, llm_config: dict) -> dict:
        return {
            "filename": doc["filename"],
            "summary": "Sintesi",
            "topics": ["topic"],
            "formulas": [],
            "figures": [],
            "keywords": [],
            "references": [],
        }

    async def _mock_plan(*args: Any, **kwargs: Any) -> tuple[str, list[dict]]:
        plan = [
            {
                "part_title": "Capitolo 1",
                "title": "1.1 Intro",
                "order_index": 0,
                "outline": {"punti": ["A"]},
                "source_filenames": ["doc.pdf"],
            },
            {
                "part_title": "Capitolo 2",
                "title": "2.1 Topic",
                "order_index": 1,
                "outline": {"punti": ["B"]},
                "source_filenames": ["notes.pdf"],
            },
        ]
        return "Doc", plan

    async def _mock_write_section(*args: Any, **kwargs: Any) -> dict:
        return {
            "title": "S",
            "part_title": "C",
            "order_index": 0,
            "latex": _LONG_LATEX,
            "outline": {},
            "source_filenames": ["doc.pdf"],
        }

    async def _mock_summarize(*args: Any, **kwargs: Any) -> list[str]:
        return ["Fatto"]

    async def _mock_overview(*args: Any, **kwargs: Any) -> _MockOverviewVerdict:
        return _MockOverviewVerdict()

    async def _mock_coherence(*args: Any, **kwargs: Any) -> dict:
        return {"approved": True, "score": 95, "issues": [], "summary": "OK"}

    async def _mock_citations(*args: Any, **kwargs: Any) -> dict:
        return {
            "approved": True,
            "score": 100,
            "uncited_user_sources": [],
            "unknown_citations": [],
            "issues": [],
            "summary": "OK",
        }

    def _mock_compile(*args: Any, **kwargs: Any) -> _MockCompileResult:
        return _MockCompileResult()

    # ── Patch and run with judge_enabled=False ─────────────────────────────
    with (
        patch.object(_cfg, "judge_enabled", False),
        patch(
            "app.agents.graph.analyze_document",
            AsyncMock(side_effect=_mock_analyze),
        ),
        patch(
            "app.agents.graph.plan_document",
            AsyncMock(side_effect=_mock_plan),
        ),
        patch(
            "app.agents.graph.write_section",
            AsyncMock(side_effect=_mock_write_section),
        ),
        patch(
            "app.agents.graph.summarize_section_context",
            AsyncMock(side_effect=_mock_summarize),
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.call_llm_structured",
            AsyncMock(side_effect=_mock_overview),
        ),
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(side_effect=_mock_coherence),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(side_effect=_mock_citations),
        ),
        patch(
            "app.agents.graph.judge_structure",
        ) as mock_judge,
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ),
        patch(
            "app.agents.graph.lint_latex",
            side_effect=lambda latex: (latex, []),
        ),
    ):
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # ── Assertions: judge_structure NEVER called ──────────────────────────
    mock_judge.assert_not_called()

    # ── Assertions: no judge keys in final state ──────────────────────────
    assert "judge_action" not in final, (
        f"judge_action should not be in final state when judge disabled: "
        f"{final.get('judge_action')}"
    )
    assert "judge_score" not in final, (
        "judge_score should not be in final state when judge disabled"
    )
    assert "judge_rounds" not in final, (
        "judge_rounds should not be in final state when judge disabled"
    )

    # ── Assertions: no judging progress events ────────────────────────────
    judging_events = [e for e in progress_events if e.get("stage") == "judging"]
    assert not judging_events, (
        f"No judging progress events expected when disabled, got: {judging_events}"
    )

    # ── Assertions: graph completed successfully ──────────────────────────
    assert "pdf_path" in final, "pdf_path key missing from final state"
    assert final["pdf_path"] is not None, "PDF should exist even without judge"
    assert "final_latex" in final, "final_latex key missing from final state"

    # ── Assertions: required stages are present, judging is absent ─────────
    stages = [e.get("stage") for e in progress_events if e.get("stage")]
    required = {"analyzing", "planning", "writing", "merge", "reviewing"}
    missing = required - set(stages)
    assert not missing, f"Missing progress stages: {missing}"
    assert "judging" not in set(stages), (
        f"judging stage should not appear when judge is disabled, "
        f"but found in stages: {stages}"
    )

    # ── Assertions: diamond outputs still present (fan-out unaffected) ────
    # overview_latex may or may not appear — it depends on whether the mocked
    # sections produce >= 2 distinct chapters (unrelated to judge_enabled).
    assert "coherence_score" in final
    assert "citation_report" in final


# ── Real-LLM E2E test (opt-in via --real-llm) ─────────────────────────────


@pytest.mark.asyncio
async def test_full_graph_with_real_llm(real_llm_config, use_real_llm):
    """Run the full graph with a real LLM provider (opt-in).

    This test is SKIPPED by default.  To run it::

        PDF2TEX_TEST_PROVIDER=openai \\
        PDF2TEX_TEST_MODEL=gpt-4o-mini \\
        pytest tests/test_full_graph_e2e.py::test_full_graph_with_real_llm --real-llm -v

    The test still mocks file I/O and compilation (write_and_compile,
    lint_latex) because those require pdflatex and a real filesystem.
    The judge is also mocked to always approve, so the graph terminates
    deterministically.

    Verifies that ALL agent nodes (analyze, plan, write, summarize,
    overview, coherence, citations) work correctly with real LLM calls.
    """
    if not use_real_llm:
        pytest.skip("Pass --real-llm to run this test with a real LLM provider")

    # ── Build initial state ────────────────────────────────────────────────
    progress_events: list[dict[str, Any]] = []

    async def _record_progress(event: dict[str, Any]) -> None:
        progress_events.append(event)

    documents = [
        {
            "filename": "appunti.pdf",
            "full_text": (
                "Il machine learning è un campo dell'intelligenza artificiale "
                "che si occupa di sviluppare algoritmi in grado di apprendere "
                "automaticamente dai dati. I principali paradigmi sono: "
                "supervisionato, non supervisionato e per rinforzo. "
            )
            * 8,
            "mandatory_figures": [],
            "figure_captions": {},
        },
        {
            "filename": "slide.pdf",
            "full_text": (
                "Le reti neurali profonde usano molti strati di neuroni "
                "artificiali per apprendere rappresentazioni gerarchiche. "
                "Il training avviene tramite backpropagation e discesa "
                "del gradiente stocastica."
            )
            * 8,
            "mandatory_figures": [],
            "figure_captions": {},
        },
    ]

    initial: GraphState = {
        "documents": documents,
        "user_prompt": "Crea un breve documento didattico sul machine learning e le reti neurali",
        "language": "italian",
        "llm_config": real_llm_config,
        "few_shot": "",
        "work_dir": str(Path("/tmp/pdf2latex_e2e_real")),
        "figures_dir": None,
        "metadata": {},
        "structure_hint": "",
        "progress": _record_progress,
        "writer_use_knowledge": False,
        "user_sources": [],
    }

    # ── Mock only file I/O and compilation; use real LLMs for agents ───────
    # judge_structure is also mocked so the graph terminates deterministically.

    async def _mock_judge(
        latex: str,
        llm_config: dict,
        pdf_path: str | None,
        compile_log: str | None,
        use_vision: bool = False,
    ) -> _MockVerdict:
        return _MockVerdict()

    def _mock_compile(
        tex_content: str,
        work_dir: Path,
        figures_src: Path | None = None,
        job_name: str = "main",
        allowed_figures: set[str] | None = None,
        bib_content: str | None = None,
    ) -> _MockCompileResult:
        return _MockCompileResult()

    with (
        patch(
            "app.agents.graph.write_and_compile",
            side_effect=_mock_compile,
        ),
        patch(
            "app.agents.graph.consolidate_references",
            return_value=[],
        ),
        patch(
            "app.agents.graph.judge_structure",
            AsyncMock(side_effect=_mock_judge),
        ),
        patch(
            "app.agents.graph.lint_latex",
            side_effect=lambda latex: (latex, []),
        ),
    ):
        # ── Run the graph with real LLM calls ──────────────────────────────
        graph = build_graph()
        final = await graph.ainvoke(initial)

    # ── Assertions: final state keys (looser — real LLM output varies) ─────

    # Core pipeline outputs must be present.
    assert "analyses" in final, (
        f"analyses key missing. Final keys: {sorted(final.keys())}"
    )
    assert "plan" in final, "plan key missing from final state"
    assert "sections" in final, "sections key missing from final state"
    assert "title" in final, "title key missing from final state"
    assert "final_latex" in final, "final_latex key missing from final state"
    assert "pdf_path" in final, "pdf_path key missing from final state"

    # Each analysis should have the expected shape.
    for analysis in final["analyses"]:
        assert "filename" in analysis
        assert "summary" in analysis
        assert "topics" in analysis
        assert len(analysis["summary"]) > 20, (
            f"Analysis summary too short: {analysis['summary'][:100]}"
        )

    # Plan should have sections.
    assert len(final["plan"]) >= 1, (
        f"Expected at least 1 planned section, got {len(final['plan'])}"
    )
    for s in final["plan"]:
        assert "title" in s
        assert "part_title" in s

    # Sections should have LaTeX content.
    assert len(final["sections"]) >= 1, (
        f"Expected at least 1 written section, got {len(final['sections'])}"
    )
    for s in final["sections"]:
        assert "latex" in s
        assert len(s["latex"]) > 100, (
            f"Section {s.get('title', '?')} LaTeX too short: {len(s['latex'])} chars"
        )

    # Diamond pattern outputs should be present.
    # overview_latex only appears when the plan has >= 2 chapters — the
    # real LLM planner might produce a single-chapter plan, so check
    # conditionally.
    unique_chapters = len({s.get("part_title", "") for s in final.get("plan", [])})
    if unique_chapters >= 2:
        assert "overview_latex" in final, (
            f"overview_latex should be set when plan has {unique_chapters} chapters"
        )
    assert "coherence_score" in final, "coherence_score should be set by coherence_node"
    assert "citation_report" in final, "citation_report should be set by citation_node"

    # Judge must have approved (mocked).
    assert final.get("judge_action") == "approve", (
        f"Expected judge_action='approve', got '{final.get('judge_action')}'"
    )
    assert final["pdf_path"] is not None, "Expected a successful PDF output"

    # ── Assertions: progress event stages ──────────────────────────────────
    stages = [e.get("stage") for e in progress_events if e.get("stage")]
    required = {
        "analyzing",
        "planning",
        "writing",
        "coherence",
        "citations",
        "merge",
        "reviewing",
        "judging",
    }
    missing = required - set(stages)
    assert not missing, f"Missing progress stages: {missing}"

    # First stage must be analyzing.
    assert stages[0] == "analyzing", (
        f"First stage should be 'analyzing', got '{stages[0]}'"
    )
    # Judge must have run (check the last 5 stages to account for varying
    # numbers of writing/lint progress events from the real LLM).
    assert "judging" in stages[-5:], (
        f"Expected 'judging' in last 5 stages, got {stages[-5:]}"
    )
