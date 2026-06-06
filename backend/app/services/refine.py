"""Quick per-section refinement: revise one section's LaTeX, recompile the doc.

This powers the "post-generation quick fix" feature: the user types a short
instruction for a specific section, an LLM rewrites only that section, then the
whole document is reassembled from the stored sections and recompiled. No PDF
re-extraction or full pipeline run is needed, so the round-trip is fast. The
previous LaTeX is kept on the section so the change can be undone.
"""

from __future__ import annotations

from typing import Any

from app.agents.prompts import SECTION_REFINE_SYSTEM
from app.agents.utils import call_llm, strip_latex_fences
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Project, Section
from app.services.assembly import recompile_project
from app.services.bibliography import strip_inline_bibliography

logger = get_logger("refine")


async def refine_section(
    session: Any,
    project: Project,
    section: Section,
    extra_prompt: str,
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    """Apply a user instruction to one section, then recompile the document."""
    user = (
        f"Lingua: {project.language or 'italian'}\n"
        f"Titolo sezione: {section.title}\n\n"
        f"Istruzione di modifica:\n{extra_prompt.strip()}\n\n"
        f"LaTeX attuale della sezione:\n{section.latex or ''}"
    )
    raw = await call_llm(
        llm_config,
        SECTION_REFINE_SYSTEM,
        user,
        temperature=settings.writer_temperature,
        label=f"refine:{section.title[:40]}",
    )
    new_latex = strip_latex_fences(raw)
    # A quick fix never introduces its own bibliography (kept once at the end).
    new_latex = strip_inline_bibliography(new_latex)
    # Keep the current version so this fix can be undone.
    section.previous_latex = section.latex
    section.latex = new_latex
    # A structured edit supersedes any whole-document main.tex override.
    project.main_tex_override = None

    result = await recompile_project(session, project)

    logger.info(
        "Refine sezione '%s' (progetto %s): compilazione %s",
        section.title,
        project.id,
        "ok" if result["success"] else "fallita",
    )
    return {
        "success": result["success"],
        "section_id": section.id,
        "latex": new_latex,
        "log_excerpt": result["log_excerpt"],
        "can_undo": True,
    }
