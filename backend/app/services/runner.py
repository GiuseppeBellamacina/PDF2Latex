"""Orchestrates a full generation run for a project: extract -> pipeline -> persist."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agents.graph import run_pipeline
from app.agents.utils import tokens
from app.core.config import settings
from app.core.encryption import decrypt_api_key
from app.core.logging import get_logger
from app.db.database import async_session
from app.db.models import (
    Figure,
    Project,
    ProjectStatus,
    ProviderConfig,
    Section,
    SectionStatus,
    Source,
)
from app.services.extractor import get_extractor
from app.services.progress import manager

logger = get_logger("runner")

# Optional few-shot style examples taken from the existing latex/ folder.
FEWSHOT_PATHS = [
    Path(__file__).resolve().parents[3] / "latex" / "parte-1-vision-language.tex",
]


def _load_few_shot() -> str:
    for p in FEWSHOT_PATHS:
        if p.exists():
            return p.read_text(encoding="utf-8")[:8000]
    return ""


async def run_generation(
    project_id: int, provider_id: int, model: str | None = None
) -> None:
    """Run the entire generation for a project, streaming progress over WS."""
    async with async_session() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return
        provider = await session.get(ProviderConfig, provider_id)
        if provider is None:
            project.status = ProjectStatus.failed
            project.error_message = "Provider non trovato"
            await session.commit()
            return

        sources = (
            (
                await session.execute(
                    select(Source).where(Source.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        figures = (
            (
                await session.execute(
                    select(Figure).where(Figure.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        # Mandatory figures grouped by source filename.
        mandatory_by_name: dict[str, list[str]] = {}
        captions_by_path: dict[str, str] = {}
        for fig in figures:
            if fig.caption:
                captions_by_path[fig.rel_path] = fig.caption
            if fig.mandatory:
                mandatory_by_name.setdefault(fig.source_filename or "", []).append(
                    fig.rel_path
                )

        llm_config = _build_llm_config(provider, model)
        few_shot = _load_few_shot()
        language = project.language

        figures_dir = settings.uploads_dir / f"project_{project_id}" / "figures"
        work_dir = settings.output_dir / f"project_{project_id}"
        work_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "title": project.name,
            "author": project.author or "",
            "subtitle": project.subtitle or "",
            "abstract": project.abstract or "",
            "cover_date": project.cover_date or "",
        }
        structure_hint = project.structure_hint or ""

        async def progress(event: dict[str, Any]) -> None:
            await manager.emit(project_id, event)

        try:
            # ---- Extraction ----
            project.status = ProjectStatus.analyzing
            await session.commit()
            await manager.emit(
                project_id,
                {"stage": "extracting", "message": "Estrazione PDF", "progress": 2},
            )

            extractor = get_extractor(
                project.extractor_backend, enable_ocr=bool(project.enable_ocr)
            )
            ordered_sources = sorted(sources, key=lambda s: s.order_index)
            n_src = len(ordered_sources)
            logger.info(
                "Progetto %s: estrazione di %d sorgenti (backend=%s, ocr=%s)",
                project_id,
                n_src,
                project.extractor_backend,
                bool(project.enable_ocr),
            )
            documents: list[dict[str, Any]] = []
            loop = asyncio.get_running_loop()
            for si, src in enumerate(ordered_sources, start=1):
                base_progress = 2 + int(3 * si / max(1, n_src))
                await manager.emit(
                    project_id,
                    {
                        "stage": "extracting",
                        "message": f"Estrazione {src.filename} ({si}/{n_src})",
                        "progress": base_progress,
                        "detail": f"documento {si} di {n_src}",
                    },
                )

                # Bridge the (synchronous) extractor's progress callbacks back
                # onto the event loop so Docling chunk milestones stream live to
                # the UI while extraction runs off-thread (keeps the loop free).
                def _progress_cb(event: dict, _base: int = base_progress) -> None:
                    event.setdefault("progress", _base)
                    asyncio.run_coroutine_threadsafe(
                        manager.emit(project_id, event), loop
                    )

                try:
                    doc = await asyncio.to_thread(
                        extractor.extract, Path(src.path), figures_dir, _progress_cb
                    )
                except Exception as exc:  # noqa: BLE001 - skip a broken file, keep going
                    logger.exception("Estrazione fallita per %s: %s", src.filename, exc)
                    await manager.emit(
                        project_id,
                        {
                            "stage": "extracting",
                            "message": f"Estrazione fallita: {src.filename}",
                            "level": "error",
                            "detail": str(exc)[:200],
                        },
                    )
                    continue
                src.n_pages = doc.n_pages
                # Figures available for this source = extracted now + mandatory picks.
                all_figs = list(
                    dict.fromkeys(doc.figures + mandatory_by_name.get(src.filename, []))
                )
                doc_captions = {
                    rel: captions_by_path[rel]
                    for rel in all_figs
                    if rel in captions_by_path
                }
                documents.append(
                    {
                        "filename": doc.filename,
                        "full_text": doc.full_text(),
                        "figures": all_figs,
                        "figure_captions": doc_captions,
                        "mandatory_figures": mandatory_by_name.get(src.filename, []),
                    }
                )
                logger.info(
                    "Estratto %s: %d pagine, %d figure, %d caratteri di testo",
                    src.filename,
                    doc.n_pages,
                    len(all_figs),
                    len(doc.full_text()),
                )
            await session.commit()

            if not documents:
                raise RuntimeError("Nessun documento estratto correttamente")

            # ---- Pipeline ----
            final = await run_pipeline(
                documents=documents,
                user_prompt=project.user_prompt or "",
                language=language,
                llm_config=llm_config,
                few_shot=few_shot,
                work_dir=work_dir,
                figures_dir=figures_dir,
                metadata=metadata,
                structure_hint=structure_hint,
                progress=progress,
            )

            # ---- Persist plan/sections ----
            await _persist_sections(session, project, final)

            tex_path = work_dir / "main.tex"
            tex_path.write_text(final.get("final_latex", ""), encoding="utf-8")
            project.output_tex_path = str(tex_path)
            project.output_pdf_path = final.get("pdf_path")
            project.status = (
                ProjectStatus.completed
                if final.get("pdf_path")
                else ProjectStatus.failed
            )
            if not final.get("pdf_path"):
                project.error_message = "Compilazione LaTeX non riuscita"
            await session.commit()

            await manager.emit(
                project_id,
                {
                    "stage": "done",
                    "message": (
                        "Completato"
                        if final.get("pdf_path")
                        else "Terminato con errori"
                    ),
                    "progress": 100,
                    "status": project.status.value,
                    "pdf": bool(final.get("pdf_path")),
                    "level": "success" if final.get("pdf_path") else "error",
                    "tokens": tokens.snapshot(),
                },
            )
            logger.info(
                "Progetto %s terminato: status=%s, token=%s",
                project_id,
                project.status.value,
                tokens.snapshot(),
            )
        except Exception as exc:  # noqa: BLE001 - report failure to UI + DB
            logger.exception("Generazione fallita per progetto %s: %s", project_id, exc)
            project.status = ProjectStatus.failed
            project.error_message = str(exc)
            await session.commit()
            await manager.emit(
                project_id,
                {
                    "stage": "error",
                    "message": str(exc),
                    "progress": 100,
                    "status": "failed",
                    "level": "error",
                },
            )


def _build_llm_config(provider: ProviderConfig, model: str | None) -> dict[str, Any]:
    api_key = None
    if provider.api_key_encrypted:
        api_key = decrypt_api_key(provider.api_key_encrypted)
    params = provider.params or {}
    return {
        "provider": provider.provider_type,
        "model": model or provider.default_model or "gpt-4o-mini",
        "api_key": api_key,
        "base_url": provider.base_url,
        "temperature": params.get("temperature", 0.2),
        "max_tokens": params.get("max_tokens"),
        "top_p": params.get("top_p"),
        "extra_params": params.get("extra_params", {}),
    }


async def _persist_sections(session, project: Project, final: dict[str, Any]) -> None:
    # Clear previous sections
    existing = (
        (await session.execute(select(Section).where(Section.project_id == project.id)))
        .scalars()
        .all()
    )
    for s in existing:
        await session.delete(s)

    written = final.get("sections", []) or []
    for s in written:
        session.add(
            Section(
                project_id=project.id,
                part_title=s.get("part_title"),
                title=s.get("title", ""),
                order_index=s.get("order_index", 0),
                latex=s.get("latex", ""),
                status=SectionStatus.completed,
            )
        )
    project.total_sections = len(written)
    project.completed_sections = len(written)
