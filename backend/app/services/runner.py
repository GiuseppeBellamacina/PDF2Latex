"""Orchestrates a full generation run for a project: extract -> pipeline -> persist.

Supports both PDF-based and research-based (web search) generation modes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agents.graph import run_pipeline
from app.agents.utils import tokens
from app.core.cancellation import CancellationError, CancellationToken
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
    WebToolConfig,
)
from app.services.extractor import get_extractor
from app.services.progress import manager
from app.services.web_extractor import fetch_and_extract

logger = get_logger("runner")

# Optional few-shot style examples taken from the existing latex/ folder.
FEWSHOT_PATHS = [
    Path(__file__).resolve().parents[3] / "latex" / "parte-1-vision-language.tex",
]


_PYTESSERACT_INSTALLED: bool | None = None


def _pytesseract_available() -> bool:
    """Return True if the pytesseract package is installed.

    On Linux/macOS this is a fast in-process check.  On Windows, however,
    pytesseract → pandas → pyarrow can access-violate when the pyarrow DLL
    is loaded concurrently with database worker threads.  Since we can't
    catch an access violation, the actual OCR work is delegated to an
    isolated subprocess on Windows — this function only reports whether the
    package exists (so we know delegation is possible).

    The result is cached for the lifetime of the process.
    """
    global _PYTESSERACT_INSTALLED
    if _PYTESSERACT_INSTALLED is not None:
        return _PYTESSERACT_INSTALLED

    import importlib.util

    _PYTESSERACT_INSTALLED = importlib.util.find_spec("pytesseract") is not None
    if not _PYTESSERACT_INSTALLED:
        logger.debug("pytesseract not installed — OCR for image sources disabled")
    return _PYTESSERACT_INSTALLED


def _ocr_image_subprocess(img_path: Path) -> str:
    """Run pytesseract OCR on an image in an isolated subprocess.

    Returns the recognised text, or ``""`` if OCR fails.

    Needed on Windows because pytesseract → pandas → pyarrow can
    access-violate when the pyarrow DLL is loaded concurrently with other
    threads (e.g. aiosqlite).  The subprocess absorbs any crash.
    """
    import subprocess

    code = (
        "import pytesseract; from PIL import Image; "
        f"print(pytesseract.image_to_string(Image.open({img_path.as_posix()!r})).strip())"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def _load_few_shot() -> str:
    for p in FEWSHOT_PATHS:
        if p.exists():
            return p.read_text(encoding="utf-8")[:8000]
    return ""


async def run_generation(
    project_id: int,
    provider_id: int,
    model: str | None = None,
    role_providers: dict[str, dict[str, Any]] | None = None,
    cancel_token: CancellationToken | None = None,
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
        # User-uploaded figures: {section_title: [(rel_path, caption), ...]}
        user_figure_placements: dict[str, list[tuple[str, str]]] = {}
        for fig in figures:
            if fig.caption:
                captions_by_path[fig.rel_path] = fig.caption
            if fig.mandatory and not fig.user_uploaded:
                mandatory_by_name.setdefault(fig.source_filename or "", []).append(
                    fig.rel_path
                )
            if fig.user_uploaded and fig.target_section_title:
                cap = fig.custom_caption or fig.caption or ""
                user_figure_placements.setdefault(fig.target_section_title, []).append(
                    (fig.rel_path, cap)
                )

        llm_config = build_llm_config(provider, model)

        # ── Thread fallback provider into main LLM config ──────────────────
        if provider.fallback_provider_id:
            fallback_prov = await session.get(
                ProviderConfig, provider.fallback_provider_id
            )
            if fallback_prov and fallback_prov.is_active:
                llm_config["fallback_llm_config"] = build_llm_config(
                    fallback_prov, None
                )
                logger.info(
                    "Provider fallback configurato: %s → %s",
                    provider.name,
                    fallback_prov.name,
                )

        # ── Build per-role LLM configs from role_providers ─────────────────
        role_configs: dict[str, dict[str, Any]] = {}
        if role_providers:
            for role, rp in role_providers.items():
                rp_id = rp.get("provider_id")
                if rp_id is None:
                    continue
                rp_provider = await session.get(ProviderConfig, rp_id)
                if rp_provider is None:
                    continue
                rp_config = build_llm_config(rp_provider, rp.get("model"))
                # Thread fallback for per-role providers too.
                if rp_provider.fallback_provider_id:
                    rp_fallback = await session.get(
                        ProviderConfig, rp_provider.fallback_provider_id
                    )
                    if rp_fallback and rp_fallback.is_active:
                        rp_config["fallback_llm_config"] = build_llm_config(
                            rp_fallback, None
                        )
                role_configs[role] = rp_config
            if role_configs:
                logger.info("Per-role providers: %s", list(role_configs.keys()))

        # ── Fallback: use project-level Web Agent provider for researcher role ──
        if "researcher" not in role_configs and project.web_agent_provider_id:
            wa_provider = await session.get(
                ProviderConfig, project.web_agent_provider_id
            )
            if wa_provider and wa_provider.is_active:
                role_configs["researcher"] = build_llm_config(
                    wa_provider, project.web_agent_model or None
                )
                logger.info(
                    "Web Agent LLM from project: provider=%s model=%s",
                    wa_provider.name,
                    project.web_agent_model or wa_provider.default_model,
                )

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
            "latex_template": project.latex_template or "default",
        }
        structure_hint = project.structure_hint or ""

        async def progress(event: dict[str, Any]) -> None:
            await manager.emit(project_id, event)

        try:
            # ---- Extraction (PDF-based, skipped if research-only) ----
            project.status = ProjectStatus.analyzing
            await session.commit()

            ordered_sources = sorted(sources, key=lambda s: s.order_index)
            n_src = len(ordered_sources)
            documents: list[dict[str, Any]] = []
            loop = asyncio.get_running_loop()

            research_active = bool(project.research_mode)
            if not ordered_sources and not research_active:
                raise RuntimeError("Nessun documento né ricerca configurata")

            # ── Build web_tool_configs for research mode ────────────────────
            # Must be constructed BEFORE the research task is created so the
            # search adapters (Wikipedia, Arxiv, user tools) are available.
            web_tool_configs: list[dict[str, Any]] = []
            if research_active:
                # ── Web Agent (orchestrator) ────────────────────────────
                web_tool_configs.append(
                    {
                        "tool_type": "web_agent",
                        "api_key": "",
                        "base_url": "",
                        "params": {
                            "max_iterations": int(project.web_agent_max_iterations),
                        },
                        "max_queries": project.research_max_queries,
                    }
                )
                # ── Wikipedia + Arxiv (always-available search backends) ────────
                web_tool_configs.append(
                    {
                        "tool_type": "wikipedia",
                        "api_key": "",
                        "base_url": "",
                        "params": {},
                    }
                )
                web_tool_configs.append(
                    {"tool_type": "arxiv", "api_key": "", "base_url": "", "params": {}}
                )
                # ── User-configured tools (Tavily / Perplexity) ──────────────
                if project.web_tool_ids:
                    for tid in project.web_tool_ids:
                        web_tool = await session.get(WebToolConfig, tid)
                        if not web_tool or not web_tool.is_active:
                            continue
                        if web_tool.tool_type in ("wikipedia", "web_agent", "arxiv"):
                            continue
                        web_tool_configs.append(
                            {
                                "tool_type": web_tool.tool_type,
                                "api_key": decrypt_api_key(web_tool.api_key_encrypted)
                                if web_tool.api_key_encrypted
                                else "",
                                "base_url": web_tool.base_url or "",
                                "params": web_tool.params or {},
                            }
                        )
                logger.info("Research mode: %d tools attivi", len(web_tool_configs))

            # ── Kick off web research in parallel with PDF extraction ─────
            # Research has NO dependency on extraction results, so it can
            # start immediately while extraction runs concurrently.
            research_task: asyncio.Task | None = None
            web_analyses: list[dict[str, Any]] | None = None
            raw_results: list[dict[str, str]] | None = None
            if research_active:
                from app.agents.researcher import research_topic

                topic = (project.user_prompt or "").strip() or project.name.strip()
                logger.info(
                    "Avvio ricerca web in parallelo all'estrazione: '%s'",
                    topic[:80],
                )
                await manager.emit(
                    project_id,
                    {
                        "stage": "researching",
                        "node": "research",
                        "message": f"Ricerca web: '{topic[:100]}'",
                        "progress": 1,
                        "detail": "in parallelo all'estrazione PDF",
                    },
                )
                research_task = asyncio.create_task(
                    research_topic(
                        topic=topic,
                        language=language,
                        llm_config=role_configs.get("researcher", llm_config),
                        web_tool_configs=web_tool_configs,
                    )
                )

            if ordered_sources:
                await manager.emit(
                    project_id,
                    {
                        "stage": "extracting",
                        "node": "extract",
                        "message": "Estrazione sorgenti",
                        "progress": 2,
                    },
                )

                # Only initialise the PDF extractor if there is at least one PDF.
                has_pdf = any(s.source_type == "pdf" for s in ordered_sources)
                extractor = None
                if has_pdf:
                    extractor = get_extractor(
                        pipeline_config=project.pipeline_config,
                        ocr_lang=project.ocr_lang,
                    )

                logger.info(
                    "Progetto %s: estrazione di %d sorgenti",
                    project_id,
                    n_src,
                )
                for si, src in enumerate(ordered_sources, start=1):
                    base_progress = 2 + int(3 * si / max(1, n_src))
                    stype = src.source_type or "pdf"
                    label = {
                        "pdf": "PDF",
                        "text": "Testo",
                        "image": "Immagine",
                        "url": "URL",
                    }.get(stype, stype)
                    await manager.emit(
                        project_id,
                        {
                            "stage": "extracting",
                            "node": "extract",
                            "message": f"{label} {src.filename} ({si}/{n_src})",
                            "progress": base_progress,
                            "detail": f"sorgente {si} di {n_src}",
                        },
                    )

                    try:
                        if stype == "pdf":

                            def _progress_cb(
                                event: dict, _base: int = base_progress
                            ) -> None:
                                event.setdefault("progress", _base)
                                asyncio.run_coroutine_threadsafe(
                                    manager.emit(project_id, event), loop
                                )

                            doc = await asyncio.to_thread(
                                extractor.extract,
                                Path(src.path),
                                figures_dir,
                                _progress_cb,
                                cancel_token,
                            )
                            src.n_pages = doc.n_pages
                            all_figs = list(
                                dict.fromkeys(
                                    doc.figures
                                    + mandatory_by_name.get(src.filename, [])
                                )
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
                                    "figure_captions": doc_captions,
                                    "mandatory_figures": mandatory_by_name.get(
                                        src.filename, []
                                    ),
                                }
                            )
                            logger.info(
                                "Estratto %s: %d pagine, %d figure",
                                src.filename,
                                doc.n_pages,
                                len(all_figs),
                            )

                        elif stype == "text":
                            text = Path(src.path).read_text(
                                encoding="utf-8", errors="replace"
                            )
                            documents.append(
                                {
                                    "filename": src.filename,
                                    "full_text": text,
                                    "figure_captions": {},
                                    "mandatory_figures": [],
                                }
                            )
                            logger.info(
                                "Letto file di testo %s: %d caratteri",
                                src.filename,
                                len(text),
                            )

                        elif stype == "url":
                            text = await fetch_and_extract(src.path)
                            documents.append(
                                {
                                    "filename": src.filename,
                                    "full_text": text,
                                    "figure_captions": {},
                                    "mandatory_figures": [],
                                }
                            )
                            logger.info(
                                "Scaricato URL %s: %d caratteri",
                                src.filename,
                                len(text),
                            )

                        elif stype == "image":
                            # Copy image into figures_dir and add as mandatory figure.
                            img_path = Path(src.path)
                            dest = figures_dir / img_path.name
                            if img_path != dest:
                                dest.write_bytes(img_path.read_bytes())
                            rel = f"figures/{img_path.name}"
                            # Attempt OCR (best-effort).
                            # pytesseract → pandas → pyarrow can access-violate
                            # on Windows during concurrent thread init (known DLL
                            # issue).  On Windows we delegate OCR to an isolated
                            # subprocess; on Linux/macOS the in-process import is
                            # safe.
                            ocr_text = ""
                            if _pytesseract_available():
                                if sys.platform == "win32":
                                    ocr_text = _ocr_image_subprocess(img_path)
                                else:
                                    try:
                                        import pytesseract
                                        from PIL import Image

                                        ocr_text = pytesseract.image_to_string(
                                            Image.open(img_path)
                                        ).strip()
                                    except Exception:
                                        pass
                                if ocr_text:
                                    logger.info(
                                        "OCR su %s: %d caratteri",
                                        src.filename,
                                        len(ocr_text),
                                    )
                            full_text = (
                                ocr_text if ocr_text else f"[Immagine: {src.filename}]"
                            )
                            documents.append(
                                {
                                    "filename": src.filename,
                                    "full_text": full_text,
                                    "figure_captions": {},
                                    "mandatory_figures": [rel],
                                }
                            )
                            logger.info("Immagine registrata: %s", src.filename)

                    except Exception as exc:  # noqa: BLE001
                        logger.exception(
                            "Estrazione fallita per %s: %s", src.filename, exc
                        )
                        await manager.emit(
                            project_id,
                            {
                                "stage": "extracting",
                                "node": "extract",
                                "message": f"Estrazione fallita: {src.filename}",
                                "level": "error",
                                "detail": str(exc)[:200],
                            },
                        )
                        continue

                await session.commit()

            # ── Await the research task (it ran in parallel with extraction) ──
            if research_task is not None:
                await manager.emit(
                    project_id,
                    {
                        "stage": "extracting",
                        "node": "extract",
                        "message": "Attendo completamento ricerca web…",
                        "progress": 4,
                    },
                )
                try:
                    web_analyses, raw_results = await research_task
                    logger.info(
                        "Ricerca web completata: %d analisi, %d raw results",
                        len(web_analyses),
                        len(raw_results),
                    )
                    if raw_results:
                        await manager.emit(
                            project_id,
                            {
                                "stage": "researching",
                                "node": "research",
                                "action": "research_results",
                                "message": f"Trovate {len(raw_results)} fonti web",
                                "progress": 6,
                                "level": "success",
                                "research_results": raw_results,
                            },
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Ricerca web fallita: %s", exc)
                    web_analyses = []
                    raw_results = []

            if not documents and not research_active:
                raise RuntimeError("Nessun documento estratto correttamente")

            # ── LLM-based figure re-scoring (vlm pipeline mode) ────────────
            pipeline_cfg = project.pipeline_config or {}
            if pipeline_cfg.get("figure_scoring") == "vlm" and figures:
                logger.info(
                    "Progetto %s: LLM figure scoring attivo su %d figure",
                    project_id,
                    len(figures),
                )
                await manager.emit(
                    project_id,
                    {
                        "stage": "extracting",
                        "node": "extract",
                        "message": f"Scoring {len(figures)} figure con LLM…",
                        "detail": "modello visione",
                    },
                )
                from app.services.figure_scorer import score_figures_with_llm

                # Build lightweight figure dicts from the DB records.
                fig_dicts = [
                    {
                        "rel_path": f.rel_path,
                        "context_text": f.context_text or "",
                        "score": f.score or 0.0,
                        "suggested": f.suggested or False,
                    }
                    for f in figures
                ]
                await score_figures_with_llm(fig_dicts, figures_dir, llm_config)
                # Write back the LLM scores to the DB.
                for fig, fd in zip(figures, fig_dicts):
                    # Only auto-set mandatory when the user hasn't manually
                    # toggled it (mandatory still matches heuristic suggested).
                    was_auto = fig.mandatory == fig.suggested
                    fig.score = fd["score"]
                    fig.suggested = fd["suggested"]
                    if was_auto:
                        fig.mandatory = fd["suggested"]
                await session.commit()
                logger.info("Progetto %s: LLM figure scoring completato", project_id)

            # ── Pipeline setup: pass pre-computed research results ────
            # When research already ran in parallel, pass pre-computed results
            # so research_node is a no-op.  Strip web_tool_configs — not needed
            # since the search already completed.
            _web_tool_configs: list[dict[str, Any]] | None = web_tool_configs
            _research_mode = bool(project.research_mode)
            if web_analyses is not None:
                _research_mode = False  # research already done
                _web_tool_configs = None

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
                judge_vision=bool(project.judge_vision),
                writer_use_knowledge=bool(project.writer_use_knowledge),
                user_sources=list(project.user_sources)
                if project.user_sources
                else None,
                research_mode=_research_mode,
                web_tool_configs=_web_tool_configs,
                user_figure_placements=user_figure_placements,
                role_configs=role_configs or None,
                web_analyses=web_analyses,
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
        except CancellationError:
            logger.info("Progetto %s cancellato dall'utente", project_id)
            project.status = ProjectStatus.failed
            project.error_message = "Generazione interrotta dall'utente"
            await session.commit()
            await manager.emit(
                project_id,
                {
                    "stage": "stopped",
                    "message": "Interrotto dall'utente",
                    "progress": project.completed_sections
                    * 100
                    // max(project.total_sections, 1)
                    if project.total_sections
                    else 0,
                    "status": "failed",
                    "level": "warning",
                },
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


def build_llm_config(provider: ProviderConfig, model: str | None) -> dict[str, Any]:
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
        "max_tokens": params.get("max_tokens")
        if params.get("max_tokens") is not None
        else settings.llm_max_tokens,
        "top_p": params.get("top_p"),
        "extra_params": params.get("extra_params", {}),
        "rpm_limit": provider.rpm_limit,  # per-provider RPM override
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
                outline=s.get("outline") or None,
                source_filenames=s.get("source_filenames") or None,
                latex=s.get("latex", ""),
                status=SectionStatus.completed,
            )
        )
    project.total_sections = len(written)
    project.completed_sections = len(written)
    # Persist the chapter overview block so reassembly (recompile/refine/
    # regenerate) keeps it instead of silently dropping it.
    project.overview_latex = final.get("overview_latex") or None
    # Persist the bibliography: the full reference pool (with citation keys) and
    # the BibTeX database of the entries actually cited, shown as an editable
    # file and shipped in the zip.
    project.references_pool = final.get("references_pool") or None
    project.bibliography_bib = final.get("bibliography_bib") or None
    # A fresh run supersedes any earlier whole-document main.tex edit.
    project.main_tex_override = None
