"""LangGraph orchestration: analyze -> plan -> write -> review -> assemble.

The graph fans out analysis (per document) and writing (per section) using
``asyncio.gather`` for parallelism, while keeping linear stages between them.
A progress callback is invoked at every stage so the API can stream updates
over WebSocket.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.analyzer import analyze_document
from app.agents.planner import plan_document
from app.agents.reviewer import review_document
from app.agents.state import GraphState
from app.agents.utils import tokens
from app.agents.writer import write_section
from app.core.logging import get_logger
from app.services.latex import assemble_document, write_and_compile
from app.services.latex_lint import lint_latex

logger = get_logger("pipeline")

MAX_REVIEW_RETRIES = 2


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

    async def _write(section: Any) -> Any:
        nonlocal done
        result = await write_section(
            section,
            documents_by_name,
            figures_by_name,
            mandatory_by_name,
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

    sections = await asyncio.gather(*[_write(s) for s in plan])
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
    return parts


def _ensure_mandatory_figures(state: GraphState, body_parts: list[str]) -> list[str]:
    """Append any mandatory figure not already referenced in the body."""
    mandatory: list[str] = []
    for d in state["documents"]:
        mandatory.extend(d.get("mandatory_figures", []))
    if not mandatory:
        return body_parts

    body_text = "\n".join(body_parts)
    missing = [p for p in dict.fromkeys(mandatory) if p not in body_text]
    if not missing:
        return body_parts

    blocks = ["\\chapter{Figure}"]
    for rel in missing:
        blocks.append(
            "\\begin{figure}[H]\\centering\n"
            f"\\includegraphics[width=0.8\\linewidth]{{{rel}}}\n"
            "\\caption{Figura tratta dal materiale sorgente.}\n"
            "\\end{figure}"
        )
    return body_parts + ["\n".join(blocks)]


async def review_node(state: GraphState) -> dict[str, Any]:
    await _emit(
        state,
        {"stage": "reviewing", "message": "Revisione e compilazione", "progress": 82},
    )

    title = state.get("title", "Documento Generato")
    language = state.get("language", "italian")
    metadata = state.get("metadata") or {}
    body_parts = _build_body(state)

    # Safety net: ensure every mandatory figure ends up in the document. Any
    # mandatory figure not already referenced is appended in a dedicated section.
    body_parts = _ensure_mandatory_figures(state, body_parts)

    latex = assemble_document(
        title=title,
        body_parts=body_parts,
        language=language,
        author=metadata.get("author") or "PDF2LaTeX",
        subtitle=metadata.get("subtitle") or "",
        abstract=metadata.get("abstract") or "",
        cover_date=metadata.get("cover_date") or "",
    )

    # Deterministic repair pass BEFORE pdflatex: fixes the most common
    # mechanical mistakes (unbalanced braces/environments, leftover \figref)
    # without spending an LLM round-trip.
    from app.core.config import settings as _settings

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
                    "message": "Compilazione riuscita",
                    "progress": 95,
                    "level": "success",
                    "tokens": tokens.snapshot(),
                },
            )
            return {"final_latex": latex, "pdf_path": result.pdf_path}

        compile_log = result.log
        if attempt < MAX_REVIEW_RETRIES:
            await _emit(
                state,
                {
                    "stage": "reviewing",
                    "message": f"Correzione errori (tentativo {attempt + 1})",
                    "progress": 85 + attempt * 3,
                    "level": "warning",
                    "detail": _compile_error_excerpt(compile_log),
                },
            )
            latex = await review_document(latex, state["llm_config"], compile_log)
            if _settings.latex_lint:
                latex, _ = lint_latex(latex)

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


# --------------------------------------------------------------------------- #
# Graph builder                                                                 #
# --------------------------------------------------------------------------- #
def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("analyze", analyze_node)
    graph.add_node("plan", plan_node)
    graph.add_node("write", write_node)
    graph.add_node("review", review_node)

    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "plan")
    graph.add_edge("plan", "write")
    graph.add_edge("write", "review")
    graph.add_edge("review", END)

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
