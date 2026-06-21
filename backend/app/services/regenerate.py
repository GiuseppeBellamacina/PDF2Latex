"""Regenerate a single section from scratch, re-reading its source PDFs.

Unlike the quick fix (which only edits the existing LaTeX), this re-extracts the
text of the section's source documents and asks the writer to author the section
again from the source material. Useful when a section came out wrong and a
simple edit is not enough. Extraction is cached, so the round-trip stays fast.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agents.writer import write_section
from app.core.logging import get_logger
from app.db.models import Figure, Project, Section, Source
from app.services.assembly import project_dirs, recompile_project
from app.services.extractor import get_extractor

logger = get_logger("regenerate")


async def regenerate_section(
    session: Any,
    project: Project,
    section: Section,
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    """Re-author one section from its source PDFs, then recompile the document."""
    source_filenames = list(section.source_filenames or [])
    if not source_filenames:
        return {
            "success": False,
            "section_id": section.id,
            "latex": section.latex or "",
            "log_excerpt": (
                "Dati sorgente non disponibili per questa sezione "
                "(progetto creato prima dell'aggiornamento). Rigenera l'intero "
                "documento per abilitare questa funzione."
            ),
            "can_undo": False,
        }

    figures_dir, _ = project_dirs(project)

    sources = (
        (await session.execute(select(Source).where(Source.project_id == project.id)))
        .scalars()
        .all()
    )
    by_name = {s.filename: s for s in sources}

    extractor = get_extractor(
        pipeline_config=project.pipeline_config,
        ocr_lang=project.ocr_lang,
    )
    documents_by_name: dict[str, str] = {}
    for fname in source_filenames:
        src = by_name.get(fname)
        if src is None:
            continue
        try:
            doc = await asyncio.to_thread(
                extractor.extract, Path(src.path), figures_dir, None
            )
        except Exception as exc:  # noqa: BLE001 - skip a broken source, keep going
            logger.warning("Riestrazione fallita per %s: %s", fname, exc)
            continue
        documents_by_name[fname] = doc.full_text()

    figures = (
        (await session.execute(select(Figure).where(Figure.project_id == project.id)))
        .scalars()
        .all()
    )
    captions_by_path = {f.rel_path: f.caption for f in figures if f.caption}
    assigned_mandatory = [
        f.rel_path
        for f in figures
        if f.mandatory and (f.source_filename or "") in source_filenames
    ]

    planned = {
        "part_title": section.part_title or "",
        "title": section.title,
        "order_index": section.order_index or 0,
        "outline": section.outline or {},
        "source_filenames": source_filenames,
    }
    # Offer the section the citable references coming from its own sources so
    # regenerated text can still \cite the relevant entries.
    section_refs = [
        ref
        for ref in (project.references_pool or [])
        if ref.get("source_filename") in source_filenames
    ]
    written = await write_section(
        planned,  # type: ignore[arg-type]
        documents_by_name,
        assigned_mandatory,
        captions_by_path,
        "",
        project.language or "italian",
        llm_config,
        available_refs=section_refs,
    )

    section.previous_latex = section.latex
    section.latex = written["latex"]
    # A structured edit supersedes any whole-document main.tex override.
    project.main_tex_override = None

    result = await recompile_project(session, project)
    logger.info(
        "Rigenerata sezione '%s' (progetto %s): compilazione %s",
        section.title,
        project.id,
        "ok" if result["success"] else "fallita",
    )
    return {
        "success": result["success"],
        "section_id": section.id,
        "latex": written["latex"],
        "log_excerpt": result["log_excerpt"],
        "can_undo": True,
    }
