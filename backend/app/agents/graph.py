"""LangGraph orchestration: analyze -> plan -> write -> review -> assemble.

The graph fans out analysis (per document) and writing (per section) using
``asyncio.gather`` for parallelism, while keeping linear stages between them.
A progress callback is invoked at every stage so the API can stream updates
over WebSocket.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.analyzer import analyze_document
from app.agents.judge import judge_structure, revise_structure
from app.agents.planner import plan_document
from app.agents.reviewer import review_document
from app.agents.state import GraphState
from app.agents.utils import tokens
from app.agents.writer import figure_latex, write_section
from app.core.logging import get_logger
from app.services.latex import assemble_document, write_and_compile
from app.services.latex_lint import lint_latex

logger = get_logger("pipeline")

MAX_REVIEW_RETRIES = 2

_FIGURE_BLOCK_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.DOTALL)
_INCLUDE_PATH_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")


def _assign_mandatory_to_sections(
    plan: list[Any], mandatory_by_name: dict[str, list[str]]
) -> list[list[str]]:
    """Give each mandatory figure to exactly ONE section.

    For every source, the sections that actually use it receive its mandatory
    figures round-robin, so a slide deck's figures are spread out instead of all
    being forced into every section that references the source (the cause of the
    same image repeating many times). Figures whose source no section uses fall
    back to the first section. Returns a per-section list aligned with ``plan``.
    """
    assigned: list[list[str]] = [[] for _ in plan]
    if not plan:
        return assigned
    for fname, figs in mandatory_by_name.items():
        target_sections = [
            i for i, s in enumerate(plan) if fname in s.get("source_filenames", [])
        ] or [0]
        for k, rel in enumerate(dict.fromkeys(figs)):
            assigned[target_sections[k % len(target_sections)]].append(rel)
    return assigned


def _dedup_figure_blocks(parts: list[str]) -> list[str]:
    """Remove repeated figure environments that point to the same image.

    The first occurrence of each image path (in document order) is kept; later
    duplicates — whether forced as mandatory or chosen by the model in several
    sections — are dropped so no figure appears twice in the document.
    """
    seen: set[str] = set()

    def _clean(part: str) -> str:
        def _sub(match: re.Match) -> str:
            block = match.group(0)
            paths = _INCLUDE_PATH_RE.findall(block)
            key = Path(paths[0]).name.lower() if paths else block
            if key in seen:
                return ""
            seen.add(key)
            return block

        return _FIGURE_BLOCK_RE.sub(_sub, part)

    return [_clean(p) for p in parts]


async def _emit(state: GraphState, event: dict[str, Any]) -> None:
    # Mirror every progress event into the server log so the backend console
    # and the UI tell the same story.
    level = event.get("level", "info")
    msg = f"[{event.get('stage', '?')}] {event.get('message', '')}"
    log = getattr(logger, level if level in ("info", "warning", "error") else "info")
    log(msg)
    cb = state.get("progress")
    if cb is not None:
        await cb(event)


# --------------------------------------------------------------------------- #
# Nodes                                                                         #
# --------------------------------------------------------------------------- #
def _compile_error_excerpt(log: str, max_lines: int = 6) -> str:
    """Pull the most relevant error lines out of a pdflatex log for the UI."""
    if not log:
        return ""
    lines = [ln for ln in log.splitlines() if ln.strip()]
    errors = [
        ln for ln in lines if ln.startswith("!") or "Error" in ln or "Undefined" in ln
    ]
    chosen = errors[:max_lines] or lines[-max_lines:]
    return " | ".join(ln.strip()[:160] for ln in chosen)


async def analyze_node(state: GraphState) -> dict[str, Any]:
    documents = state["documents"]
    llm_config = state["llm_config"]
    await _emit(
        state,
        {
            "stage": "analyzing",
            "message": f"Analisi di {len(documents)} documenti",
            "progress": 5,
            "detail": ", ".join(d["filename"] for d in documents)[:200],
        },
    )

    tasks = [analyze_document(doc, llm_config) for doc in documents]
    analyses = await asyncio.gather(*tasks)

    n_topics = sum(len(a["topics"]) for a in analyses)
    await _emit(
        state,
        {
            "stage": "analyzing",
            "message": f"Analizzati {len(analyses)} documenti",
            "progress": 25,
            "level": "success",
            "detail": f"{n_topics} argomenti individuati",
        },
    )
    return {"analyses": list(analyses)}


async def plan_node(state: GraphState) -> dict[str, Any]:
    await _emit(
        state,
        {"stage": "planning", "message": "Pianificazione struttura", "progress": 30},
    )

    title, plan = await plan_document(
        analyses=[dict(a) for a in state["analyses"]],
        user_prompt=state.get("user_prompt", ""),
        language=state.get("language", "italian"),
        llm_config=state["llm_config"],
        structure_hint=state.get("structure_hint", ""),
    )

    # Prefer the user-provided document title if present.
    meta_title = (state.get("metadata") or {}).get("title")
    if meta_title:
        title = meta_title

    await _emit(
        state,
        {
            "stage": "planning",
            "message": f"Struttura: {len(plan)} sezioni",
            "progress": 40,
            "level": "success",
            "plan": [
                {"part_title": s["part_title"], "title": s["title"]} for s in plan
            ],
        },
    )
    return {"title": title, "plan": plan}


async def write_node(state: GraphState) -> dict[str, Any]:
    plan = state["plan"]
    documents_by_name = {
        d["filename"]: d.get("full_text", "") for d in state["documents"]
    }
    figures_by_name = {d["filename"]: d.get("figures", []) for d in state["documents"]}
    mandatory_by_name = {
        d["filename"]: d.get("mandatory_figures", []) for d in state["documents"]
    }
    # Assign each mandatory figure to exactly one section (round-robin across the
    # sections that use its source) so no image is forced into many sections.
    assigned_mandatory = _assign_mandatory_to_sections(plan, mandatory_by_name)
    # Aggregate every figure's OCR caption so the writer knows what each ID
    # actually depicts when deciding which to include.
    captions_by_path: dict[str, str] = {}
    for d in state["documents"]:
        captions_by_path.update(d.get("figure_captions", {}) or {})
    few_shot = state.get("few_shot", "")
    language = state.get("language", "italian")
    llm_config = state["llm_config"]

    await _emit(
        state, {"stage": "writing", "message": "Scrittura sezioni", "progress": 45}
    )

    total = len(plan)
    done = 0
    lock = asyncio.Lock()

    async def _write(idx: int, section: Any) -> Any:
        nonlocal done
        result = await write_section(
            section,
            documents_by_name,
            figures_by_name,
            assigned_mandatory[idx],
            captions_by_path,
            few_shot,
            language,
            llm_config,
        )
        async with lock:
            done += 1
            prog = 45 + int(35 * done / max(1, total))
            await _emit(
                state,
                {
                    "stage": "writing",
                    "message": f"Scritta sezione: {section['title']}",
                    "progress": prog,
                    "completed": done,
                    "total": total,
                },
            )
        return result

    sections = await asyncio.gather(*[_write(i, s) for i, s in enumerate(plan)])
    sections = sorted(sections, key=lambda s: s["order_index"])
    return {"sections": list(sections)}


def _build_body(state: GraphState) -> list[str]:
    parts: list[str] = []
    current_part: str | None = None
    for s in state["sections"]:
        part_title = s.get("part_title")
        if part_title and part_title != current_part:
            parts.append(f"\\chapter{{{part_title}}}")
            current_part = part_title
        parts.append(s["latex"])
    # Drop any image that ended up referenced in more than one section.
    return _dedup_figure_blocks(parts)


def _ensure_mandatory_figures(state: GraphState, body_parts: list[str]) -> list[str]:
    """Append any mandatory figure not already referenced anywhere in the body."""
    mandatory: list[str] = []
    for d in state["documents"]:
        mandatory.extend(d.get("mandatory_figures", []))
    if not mandatory:
        return body_parts

    body_text = "\n".join(body_parts)
    missing = [
        p
        for p in dict.fromkeys(mandatory)
        if Path(p).name.lower() not in body_text.lower()
    ]
    if not missing:
        return body_parts

    blocks = ["\\chapter{Figure}"]
    for rel in missing:
        blocks.append(figure_latex(rel, ""))
    return body_parts + ["\n".join(blocks)]


def _assemble_initial(state: GraphState) -> str:
    """Assemble the monolithic document from the written sections (first pass)."""
    title = state.get("title", "Documento Generato")
    language = state.get("language", "italian")
    metadata = state.get("metadata") or {}
    body_parts = _build_body(state)
    # Safety net: ensure every mandatory figure ends up in the document. Any
    # mandatory figure not already referenced is appended in a dedicated section.
    body_parts = _ensure_mandatory_figures(state, body_parts)
    return assemble_document(
        title=title,
        body_parts=body_parts,
        language=language,
        author=metadata.get("author") or "PDF2LaTeX",
        subtitle=metadata.get("subtitle") or "",
        abstract=metadata.get("abstract") or "",
        cover_date=metadata.get("cover_date") or "",
    )


async def review_node(state: GraphState) -> dict[str, Any]:
    from app.core.config import settings as _settings

    # First pass assembles from sections; later passes recompile the document
    # the judge revised (kept in ``final_latex``).
    is_revision = bool(state.get("final_latex"))
    if is_revision:
        await _emit(
            state,
            {
                "stage": "reviewing",
                "message": "Ricompilazione dopo revisione strutturale",
                "progress": 90,
            },
        )
        latex = state["final_latex"]
    else:
        await _emit(
            state,
            {
                "stage": "reviewing",
                "message": "Revisione e compilazione",
                "progress": 82,
            },
        )
        latex = _assemble_initial(state)

    # Deterministic repair pass BEFORE pdflatex: fixes the most common
    # mechanical mistakes (unbalanced braces/environments, leftover \figref)
    # without spending an LLM round-trip.

    if _settings.latex_lint:
        latex, lint_notes = lint_latex(latex)
        if lint_notes:
            await _emit(
                state,
                {
                    "stage": "reviewing",
                    "message": f"Lint LaTeX: {len(lint_notes)} correzioni",
                    "progress": 83,
                    "level": "info",
                    "detail": "; ".join(lint_notes[:8]),
                },
            )

    work_dir = Path(state.get("work_dir", "storage/output/_tmp"))  # type: ignore[arg-type]
    figures_src = state.get("figures_dir")
    figures_path = Path(figures_src) if figures_src else None

    compile_log = ""
    for attempt in range(MAX_REVIEW_RETRIES + 1):
        result = write_and_compile(
            latex, work_dir, figures_src=figures_path, job_name="main"
        )
        if result.success:
            await _emit(
                state,
                {
                    "stage": "reviewing",
                    "message": (
                        "Ricompilazione riuscita"
                        if is_revision
                        else "Compilazione riuscita"
                    ),
                    "progress": 92 if is_revision else 88,
                    "level": "success",
                    "tokens": tokens.snapshot(),
                },
            )
            # Remember the last version that compiled, so a later (judge)
            # revision that breaks compilation can be safely rolled back.
            return {
                "final_latex": latex,
                "pdf_path": result.pdf_path,
                "good_latex": latex,
                "good_pdf": result.pdf_path,
                "compile_log": result.log,
            }

        compile_log = result.log
        if attempt < MAX_REVIEW_RETRIES:
            await _emit(
                state,
                {
                    "stage": "reviewing",
                    "message": f"Correzione errori (tentativo {attempt + 1})",
                    "progress": 84 + attempt * 2,
                    "level": "warning",
                    "detail": _compile_error_excerpt(compile_log),
                },
            )
            latex = await review_document(latex, state["llm_config"], compile_log)
            if _settings.latex_lint:
                latex, _ = lint_latex(latex)

    # A judge revision failed to compile even after retries: roll back to the
    # last version that produced a PDF instead of shipping a broken document.
    if is_revision and state.get("good_pdf"):
        await _emit(
            state,
            {
                "stage": "reviewing",
                "message": "Revisione strutturale scartata (non compilava)",
                "progress": 94,
                "level": "warning",
                "detail": "Mantengo la versione precedente che compilava.",
            },
        )
        return {
            "final_latex": state["good_latex"],
            "pdf_path": state["good_pdf"],
            "compile_log": state.get("compile_log", ""),
        }

    # Failed to compile after retries: still return the latex for inspection.
    await _emit(
        state,
        {
            "stage": "reviewing",
            "message": "Compilazione non riuscita",
            "progress": 95,
            "level": "error",
            "detail": _compile_error_excerpt(compile_log),
        },
    )
    return {"final_latex": latex, "pdf_path": None, "compile_log": compile_log}


async def judge_node(state: GraphState) -> dict[str, Any]:
    """Evaluate the document's overall structure and request a revision if needed."""
    from app.core.config import settings as _settings

    rounds = state.get("judge_rounds", 0)
    await _emit(
        state,
        {
            "stage": "judging",
            "message": "Il giudice esamina il PDF compilato",
            "progress": 90,
            "detail": (
                "analisi visiva delle pagine"
                if _settings.judge_vision
                else "analisi di struttura e layout"
            ),
        },
    )

    verdict = await judge_structure(
        state["final_latex"],
        state["llm_config"],
        state.get("pdf_path"),
        state.get("compile_log"),
    )
    if verdict.approved or not verdict.issues:
        await _emit(
            state,
            {
                "stage": "judging",
                "message": f"Struttura approvata (punteggio {verdict.score}/100)",
                "progress": 96,
                "level": "success",
                "detail": verdict.summary[:200] or None,
            },
        )
        return {"judge_action": "approve", "judge_score": verdict.score}

    await _emit(
        state,
        {
            "stage": "judging",
            "message": f"Revisione struttura: {len(verdict.issues)} problemi",
            "progress": 91,
            "level": "warning",
            "detail": "; ".join(verdict.issues[:6]),
        },
    )
    revised = await revise_structure(
        state["final_latex"], verdict.issues, state["llm_config"]
    )
    if _settings.latex_lint:
        revised, _ = lint_latex(revised)
    return {
        "final_latex": revised,
        "judge_rounds": rounds + 1,
        "judge_action": "revise",
        "judge_score": verdict.score,
    }


def _after_review(state: GraphState) -> str:
    """Route to the judge after a successful first compile, else finish."""
    from app.core.config import settings as _settings

    if not _settings.judge_enabled:
        return END
    # Don't judge a document that didn't compile.
    if not state.get("pdf_path"):
        return END
    # Stop once the allowed structural-revision rounds are exhausted.
    if state.get("judge_rounds", 0) >= _settings.judge_max_iterations:
        return END
    return "judge"


def _after_judge(state: GraphState) -> str:
    """Loop back to review+compile when the judge requested a revision."""
    if state.get("judge_action") == "revise":
        return "review"
    return END


# --------------------------------------------------------------------------- #
# Graph builder                                                                 #
# --------------------------------------------------------------------------- #
def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("analyze", analyze_node)
    graph.add_node("plan", plan_node)
    graph.add_node("write", write_node)
    graph.add_node("review", review_node)
    graph.add_node("judge", judge_node)

    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "plan")
    graph.add_edge("plan", "write")
    graph.add_edge("write", "review")
    graph.add_conditional_edges("review", _after_review, {"judge": "judge", END: END})
    graph.add_conditional_edges("judge", _after_judge, {"review": "review", END: END})

    return graph.compile()


async def run_pipeline(
    documents: list[dict[str, Any]],
    user_prompt: str,
    language: str,
    llm_config: dict[str, Any],
    few_shot: str,
    work_dir: Path,
    figures_dir: Path | None,
    metadata: dict[str, Any] | None = None,
    structure_hint: str = "",
    progress=None,
) -> dict[str, Any]:
    """Run the full pipeline and return the final state."""
    app = build_graph()
    initial: dict[str, Any] = {
        "documents": documents,
        "user_prompt": user_prompt,
        "language": language,
        "llm_config": llm_config,
        "few_shot": few_shot,
        "work_dir": str(work_dir),
        "figures_dir": str(figures_dir) if figures_dir else None,
        "metadata": metadata or {},
        "structure_hint": structure_hint,
        "progress": progress,
    }
    final = await app.ainvoke(initial)
    return final
