"""Shared helpers to reassemble + recompile a document from stored sections.

Several post-generation actions need to rebuild the whole document from the
section rows kept in the database and recompile it: the quick fix (refine), the
manual compile retry (recompile), the per-section regenerate and the undo. They
all share the assembly + figure-handling + compile path defined here so the
behaviour stays consistent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agents.reviewer import review_document
from app.agents.utils import compile_error_excerpt
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Figure, Project, ProjectStatus, Section
from app.services.bibliography import cited_keys, strip_inline_bibliography
from app.services.latex import assemble_document, write_and_compile
from app.services.latex_lint import lint_latex

logger = get_logger("assembly")


def project_dirs(project: Project) -> tuple[Path, Path]:
    """Return ``(figures_dir, work_dir)`` for a project, creating the work dir."""
    figures_dir = settings.uploads_dir / f"project_{project.id}" / "figures"
    work_dir = settings.output_dir / f"project_{project.id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    return figures_dir, work_dir


async def load_sections(session: Any, project_id: int) -> list[Section]:
    """Load all sections of a project ordered by ``order_index``."""
    rows = (
        (
            await session.execute(
                select(Section)
                .where(Section.project_id == project_id)
                .order_by(Section.order_index)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def load_allowed_figures(session: Any, project_id: int) -> set[str] | None:
    """Return the set of figure file names the user marked as mandatory."""
    rows = (
        (
            await session.execute(
                select(Figure).where(
                    Figure.project_id == project_id, Figure.mandatory.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    return {Path(f.rel_path).name for f in rows} or None


def assemble_from_sections(project: Project, sections: list[Section]) -> str:
    """Rebuild the full monolithic document from the stored section rows.

    Any bibliography the model left inside a section is stripped; the single,
    structured bibliography is appended at the very end when the document both
    has a BibTeX database and actually cites something.
    """
    body_parts: list[str] = []
    # Per-chapter synopsis page (if any) goes right after the TOC.
    if project.overview_latex:
        body_parts.append(project.overview_latex)
    current_part: str | None = None
    for s in sections:
        if s.part_title and s.part_title != current_part:
            body_parts.append(f"\\chapter{{{s.part_title}}}")
            current_part = s.part_title
        body_parts.append(strip_inline_bibliography(s.latex or ""))
    has_bibliography = bool(project.bibliography_bib) and bool(
        cited_keys("\n".join(body_parts))
    )
    return assemble_document(
        title=project.name or "Documento",
        body_parts=body_parts,
        language=project.language or "italian",
        author=project.author or "PDF2LaTeX",
        subtitle=project.subtitle or "",
        abstract=project.abstract or "",
        cover_date=project.cover_date or "",
        has_bibliography=has_bibliography,
    )


async def recompile_project(
    session: Any,
    project: Project,
    *,
    llm_config: dict[str, Any] | None = None,
    review_passes: int = 0,
    full_latex: str | None = None,
) -> dict[str, Any]:
    """Reassemble (unless ``full_latex`` is given) and recompile the document.

    When ``llm_config`` is provided and the first compile fails, up to
    ``review_passes`` LLM repair rounds are attempted (same loop as the pipeline).
    Updates the project's output paths and status, then commits.
    """
    if full_latex is None:
        # A whole-document edit (main.tex from the file editor) wins over the
        # per-section reassembly; otherwise rebuild from the stored sections.
        if project.main_tex_override:
            full_latex = project.main_tex_override
        else:
            sections = await load_sections(session, project.id)
            full_latex = assemble_from_sections(project, sections)
    if settings.latex_lint:
        full_latex, _ = lint_latex(full_latex)

    figures_dir, work_dir = project_dirs(project)
    allowed = await load_allowed_figures(session, project.id)
    bib_content = project.bibliography_bib or ""

    result = write_and_compile(
        full_latex,
        work_dir,
        figures_src=figures_dir,
        allowed_figures=allowed,
        bib_content=bib_content,
    )
    attempts = 0
    while not result.success and attempts < review_passes and llm_config is not None:
        full_latex = await review_document(full_latex, llm_config, result.log)
        if settings.latex_lint:
            full_latex, _ = lint_latex(full_latex)
        result = write_and_compile(
            full_latex,
            work_dir,
            figures_src=figures_dir,
            allowed_figures=allowed,
            bib_content=bib_content,
        )
        attempts += 1

    project.output_tex_path = str(work_dir / "main.tex")
    if result.success:
        project.output_pdf_path = result.pdf_path
        project.status = ProjectStatus.completed
        project.error_message = None
    else:
        project.status = ProjectStatus.failed
        project.error_message = "Compilazione LaTeX non riuscita"
    await session.commit()

    logger.info(
        "Ricompilazione progetto %s: %s (%d round di correzione)",
        project.id,
        "ok" if result.success else "fallita",
        attempts,
    )
    return {
        "success": result.success,
        "pdf": bool(result.success),
        "log_excerpt": "" if result.success else compile_error_excerpt(result.log),
    }
