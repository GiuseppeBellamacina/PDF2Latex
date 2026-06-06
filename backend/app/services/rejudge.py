"""Manual "run the judge again" action for a finished project.

Re-runs the structural judge on the current document and, when it finds
problems, applies a structural revision and recompiles — the same logic the
pipeline runs automatically, but triggered on demand from the UI so the user can
push the document one more round without redoing analysis/planning/writing.
"""

from __future__ import annotations

from typing import Any

from app.agents.judge import judge_structure, revise_structure
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Project
from app.services.assembly import (
    assemble_from_sections,
    load_sections,
    recompile_project,
)
from app.services.latex_lint import lint_latex

logger = get_logger("rejudge")


async def rejudge_project(
    session: Any,
    project: Project,
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    """Judge the current document; revise + recompile if issues are found."""
    sections = await load_sections(session, project.id)
    full_latex = assemble_from_sections(project, sections)

    verdict = await judge_structure(
        full_latex,
        llm_config,
        project.output_pdf_path,
        None,
        use_vision=bool(project.judge_vision),
    )

    if verdict.approved or not verdict.issues:
        logger.info(
            "Rejudge progetto %s: approvato (score %s)", project.id, verdict.score
        )
        return {
            "applied": False,
            "approved": True,
            "score": verdict.score,
            "issues": [],
            "summary": verdict.summary,
            "success": bool(project.output_pdf_path),
        }

    revised = await revise_structure(full_latex, verdict.issues, llm_config)
    if settings.latex_lint:
        revised, _ = lint_latex(revised)

    result = await recompile_project(
        session,
        project,
        llm_config=llm_config,
        review_passes=1,
        full_latex=revised,
    )
    logger.info(
        "Rejudge progetto %s: revisione applicata (%d problemi), compilazione %s",
        project.id,
        len(verdict.issues),
        "ok" if result["success"] else "fallita",
    )
    return {
        "applied": True,
        "approved": False,
        "score": verdict.score,
        "issues": verdict.issues,
        "summary": verdict.summary,
        "success": result["success"],
        "log_excerpt": result["log_excerpt"],
    }
