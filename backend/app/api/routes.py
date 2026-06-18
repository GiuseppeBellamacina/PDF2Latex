"""REST API routes: providers, projects, upload, download."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    FigureUpdate,
    GenerateActionRequest,
    ProjectFileOut,
    ProjectFileSave,
    ProjectOut,
    ProjectSummary,
    ProjectUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderTestRequest,
    ProviderUpdate,
    SectionRefineRequest,
    WebToolCreate,
    WebToolOut,
    WebToolUpdate,
)
from app.core.config import settings
from app.core.encryption import encrypt_api_key
from app.core.llm_factory import LLMConfig, test_llm_connection
from app.db.database import get_db
from app.db.models import (
    Figure,
    Project,
    ProjectStatus,
    ProviderConfig,
    Section,
    Source,
    WebToolConfig,
)
from app.services import pipeline as pipeline_registry
from app.services.assembly import (
    assemble_from_sections,
    load_sections,
    recompile_project,
)
from app.services.extractor import (
    available_backends,
    extract_figures,
    pdf_page_count,
)
from app.services.latex import build_project_zip, slugify_title, split_into_part_files
from app.services.latex_templates import list_templates
from app.services.refine import refine_section
from app.services.regenerate import regenerate_section
from app.services.rejudge import rejudge_project
from app.services.runner import build_llm_config

router = APIRouter()


def _parse_user_sources(raw: str) -> list[dict[str, str]]:
    """Parse user-provided bibliographic sources from a textarea.

    Each line should be: ``Author(s) | Title | Year | Venue (optional)``.
    Lines starting with ``#`` are treated as comments and skipped.
    """
    sources: list[dict[str, str]] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        authors, title, year = parts[0], parts[1], parts[2]
        venue = parts[3] if len(parts) > 3 else ""
        if not authors or not title or not year:
            continue
        sources.append(
            {"authors": authors, "title": title, "year": year, "venue": venue}
        )
    return sources


@router.get("/backends")
async def list_backends():
    """Report which extractor backends are installed/usable."""
    return available_backends()


@router.get("/pipeline")
async def describe_pipeline(
    project_key: str | None = None, db: AsyncSession = Depends(get_db)
):
    """Describe the composable extraction pipeline for the dashboard.

    Returns every stage with its tools, each annotated with whether it is
    currently installed/usable and an install hint when it is not. When
    ``project_key`` is given, the response reflects that project's saved
    selection; otherwise the global defaults are used.
    """
    config = None
    if project_key:
        project = await _project_by_key(db, project_key)
        config = project.pipeline_config
    return {
        "default": pipeline_registry.default_pipeline_config(),
        "stages": pipeline_registry.describe_pipeline(config),
    }


# --------------------------- Providers ------------------------------------- #
def _provider_out(p: ProviderConfig) -> ProviderOut:
    return ProviderOut(
        id=p.id,
        name=p.name,
        provider_type=p.provider_type,
        base_url=p.base_url,
        default_model=p.default_model,
        params=p.params,
        is_active=p.is_active,
        has_api_key=bool(p.api_key_encrypted),
    )


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ProviderConfig))).scalars().all()
    return [_provider_out(p) for p in rows]


@router.post("/providers", response_model=ProviderOut)
async def create_provider(payload: ProviderCreate, db: AsyncSession = Depends(get_db)):
    provider = ProviderConfig(
        name=payload.name,
        provider_type=payload.provider_type,
        base_url=payload.base_url,
        default_model=payload.default_model,
        params=payload.params,
        is_active=payload.is_active,
        api_key_encrypted=encrypt_api_key(payload.api_key) if payload.api_key else None,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return _provider_out(provider)


@router.put("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: int, payload: ProviderUpdate, db: AsyncSession = Depends(get_db)
):
    provider = await db.get(ProviderConfig, provider_id)
    if provider is None:
        raise HTTPException(404, "Provider non trovato")
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        key = data.pop("api_key")
        provider.api_key_encrypted = encrypt_api_key(key) if key else None
    for field, value in data.items():
        setattr(provider, field, value)
    await db.commit()
    await db.refresh(provider)
    return _provider_out(provider)


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    provider = await db.get(ProviderConfig, provider_id)
    if provider is None:
        raise HTTPException(404, "Provider non trovato")
    await db.delete(provider)
    await db.commit()
    return {"ok": True}


@router.post("/providers/test")
async def test_provider(payload: ProviderTestRequest):
    config = LLMConfig(
        provider=payload.provider_type,
        model=payload.model,
        api_key=payload.api_key,
        base_url=payload.base_url,
    )
    return await test_llm_connection(config)


# --------------------------- Web Tools ------------------------------------- #
def _web_tool_out(p: WebToolConfig) -> WebToolOut:
    return WebToolOut(
        id=p.id,
        name=p.name,
        tool_type=p.tool_type,
        base_url=p.base_url,
        params=p.params,
        is_active=p.is_active,
        has_api_key=bool(p.api_key_encrypted),
    )


@router.get("/webtools", response_model=list[WebToolOut])
async def list_web_tools(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(WebToolConfig))).scalars().all()
    return [_web_tool_out(p) for p in rows]


@router.post("/webtools", response_model=WebToolOut)
async def create_web_tool(payload: WebToolCreate, db: AsyncSession = Depends(get_db)):
    tool = WebToolConfig(
        name=payload.name,
        tool_type=payload.tool_type,
        base_url=payload.base_url,
        params=payload.params,
        is_active=payload.is_active,
        api_key_encrypted=encrypt_api_key(payload.api_key) if payload.api_key else None,
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return _web_tool_out(tool)


@router.put("/webtools/{tool_id}", response_model=WebToolOut)
async def update_web_tool(
    tool_id: int, payload: WebToolUpdate, db: AsyncSession = Depends(get_db)
):
    tool = await db.get(WebToolConfig, tool_id)
    if tool is None:
        raise HTTPException(404, "Web tool non trovato")
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        key = data.pop("api_key")
        tool.api_key_encrypted = encrypt_api_key(key) if key else None
    for field, value in data.items():
        setattr(tool, field, value)
    await db.commit()
    await db.refresh(tool)
    return _web_tool_out(tool)


@router.delete("/webtools/{tool_id}")
async def delete_web_tool(tool_id: int, db: AsyncSession = Depends(get_db)):
    tool = await db.get(WebToolConfig, tool_id)
    if tool is None:
        raise HTTPException(404, "Web tool non trovato")
    await db.delete(tool)
    await db.commit()
    return {"ok": True}


# --------------------------- Projects -------------------------------------- #
@router.get("/templates")
async def list_latex_templates():
    """Return available LaTeX document templates for the UI selector."""
    return list_templates()


@router.post("/projects", response_model=ProjectOut)
async def create_project(
    name: str = Form(...),
    user_prompt: str = Form(""),
    language: str = Form("italian"),
    author: str = Form(""),
    subtitle: str = Form(""),
    abstract: str = Form(""),
    cover_date: str = Form(""),
    structure_hint: str = Form(""),
    extractor_backend: str = Form("hybrid"),
    ocr_lang: str = Form(""),
    latex_template: str = Form("default"),
    writer_use_knowledge: bool = Form(False),
    user_sources: str = Form(""),
    research_mode: bool = Form(False),
    web_tool_ids: str = Form(""),
    research_max_queries: int = Form(0),
    urls: str = Form(""),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    has_files = any((f.filename or "").strip() for f in files)
    url_list = [u.strip() for u in urls.split("\n") if u.strip()]
    if not has_files and not url_list and not research_mode:
        raise HTTPException(400, "Nessuna fonte caricata e ricerca web non attiva")

    # Parse web_tool_ids from comma-separated string (e.g. "1,2,3").
    _parsed_tool_ids: list[int] = []
    if web_tool_ids.strip():
        for raw in web_tool_ids.split(","):
            raw = raw.strip()
            if raw:
                try:
                    _parsed_tool_ids.append(int(raw))
                except ValueError:
                    raise HTTPException(400, f"ID web tool non valido: {raw}")

    # Validate web_tool_ids when research_mode is enabled.
    if research_mode and _parsed_tool_ids:
        for tid in _parsed_tool_ids:
            web_tool = await db.get(WebToolConfig, tid)
            if web_tool is None:
                raise HTTPException(404, f"Web tool {tid} non trovato")
            if not web_tool.is_active:
                raise HTTPException(400, f"Il web tool '{web_tool.name}' non è attivo")

    total_source_count = len([f for f in files if (f.filename or "").strip()]) + len(
        url_list
    )
    project = Project(
        name=name,
        user_prompt=user_prompt or None,
        language=language,
        author=author or None,
        subtitle=subtitle or None,
        abstract=abstract or None,
        cover_date=cover_date or None,
        structure_hint=structure_hint or None,
        extractor_backend=extractor_backend or "hybrid",
        ocr_lang=ocr_lang or None,
        latex_template=latex_template or "default",
        writer_use_knowledge=writer_use_knowledge,
        user_sources=_parse_user_sources(user_sources)
        if user_sources.strip()
        else None,
        research_mode=bool(research_mode),
        web_tool_ids=_parsed_tool_ids if _parsed_tool_ids else None,
        research_max_queries=research_max_queries if research_max_queries > 0 else None,
        status=ProjectStatus.uploaded,
        total_sources=total_source_count,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    dest_dir = settings.uploads_dir / f"project_{project.id}"
    figures_dir = dest_dir / "figures"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # ── Helper: classify a filename by extension ────────────────────────
    def _classify(fname: str) -> str:
        ext = Path(fname).suffix.lower()
        if ext in (".pdf",):
            return "pdf"
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"):
            return "image"
        # Everything else (txt, md, json, csv, py, js, etc.) is text.
        return "text"

    # ── Phase 1: write all files to disk, collect metadata ──────────────
    file_infos: list[dict] = []
    src_idx = 0  # global order index across files + urls
    for upload in files:
        fname = (upload.filename or "").strip()
        if not fname:
            continue
        safe_name = Path(fname).name
        target = dest_dir / safe_name
        content = await upload.read()
        target.write_bytes(content)
        stype = _classify(fname)
        file_infos.append(
            {
                "idx": src_idx,
                "filename": safe_name,
                "target": target,
                "source_type": stype,
            }
        )
        src_idx += 1

    # Add URLs as source entries — use a short, readable filename derived from
    # the domain + path stem so the planner LLM reliably copies it into
    # source_filenames (a full https://... URL would often be mangled).
    url_infos: list[dict] = []
    for url in url_list:
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                url_slug = f"web_{hashlib.md5(url.encode()).hexdigest()[:8]}"
            else:
                domain = parsed.netloc.replace(".", "_")
                path_stem = parsed.path.rstrip("/").split("/")[-1] or "page"
                url_slug = f"{domain}_{path_stem}"[:64]
        except Exception:
            url_slug = f"web_{hashlib.md5(url.encode()).hexdigest()[:8]}"
        url_infos.append(
            {
                "idx": src_idx,
                "filename": url_slug,
                "target": url,
                "source_type": "url",
            }
        )
        src_idx += 1

    if not file_infos and not url_infos and not research_mode:
        raise HTTPException(400, "Nessuna fonte valida caricata")

    # ── Phase 2: create Source records ──────────────────────────────────
    async def _create_source(info: dict) -> Source:
        n_pages = 0
        if info["source_type"] == "pdf" and isinstance(info["target"], Path):
            n_pages = await run_in_threadpool(pdf_page_count, info["target"])
        return Source(
            project_id=project.id,
            filename=info["filename"],
            path=str(info["target"]),
            order_index=info["idx"],
            n_pages=n_pages,
            source_type=info["source_type"],
        )

    all_infos = file_infos + url_infos
    sources = await asyncio.gather(*[_create_source(info) for info in all_infos])
    for source in sources:
        db.add(source)
    await db.flush()

    # ── Phase 3: extract figures only from PDFs ────────────────────────
    pdf_infos = [i for i in file_infos if i["source_type"] == "pdf"]
    pdf_sources = [s for s, i in zip(sources, file_infos) if i["source_type"] == "pdf"]

    async def _extract_one(source: Source, info: dict) -> tuple[Source, list]:
        try:
            figs = await run_in_threadpool(extract_figures, info["target"], figures_dir)
        except Exception:
            figs = []
        return source, figs

    all_fig_pairs = await asyncio.gather(
        *[_extract_one(pdf_sources[i], pdf_infos[i]) for i in range(len(pdf_sources))]
    )

    # ── Phase 4: create Figure records ─────────────────────────────────
    fig_order = 0
    for source, figs in all_fig_pairs:
        for fig in figs:
            db.add(
                Figure(
                    project_id=project.id,
                    source_id=source.id,
                    source_filename=source.filename,
                    rel_path=fig.rel_path,
                    page=fig.page,
                    order_index=fig_order,
                    caption=fig.caption or None,
                    score=fig.score,
                    suggested=fig.suggested,
                    mandatory=fig.suggested,
                    context_text=fig.context_text or None,
                )
            )
            fig_order += 1

    await db.commit()
    return await _get_project_full(db, project.id)


async def _project_by_key(db: AsyncSession, key: str) -> Project:
    """Resolve a project by its opaque public identifier (404 if missing)."""
    result = await db.execute(select(Project).where(Project.public_id == key))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "Progetto non trovato")
    return project


@router.patch("/projects/{project_key}", response_model=ProjectOut)
async def update_project(
    project_key: str, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)
):
    project = await _project_by_key(db, project_key)
    project_id = project.id

    data = payload.model_dump(exclude_unset=True)
    source_order = data.pop("source_order", None)
    mandatory_ids = data.pop("mandatory_figure_ids", None)

    if "pipeline_config" in data:
        cfg = data.pop("pipeline_config")
        project.pipeline_config = (
            pipeline_registry.normalize_pipeline_config(cfg) if cfg else None
        )

    if "latex_template" in data:
        project.latex_template = data.pop("latex_template") or "default"

    for field, value in data.items():
        setattr(project, field, value)

    # Validate web_tool_ids only when research_mode or web_tool_ids were
    # explicitly changed in this request (not on unrelated PATCH calls).
    if "research_mode" in data or "web_tool_ids" in data:
        if project.research_mode and project.web_tool_ids:
            for tid in project.web_tool_ids:
                web_tool = await db.get(WebToolConfig, tid)
                if web_tool is None:
                    raise HTTPException(404, f"Web tool {tid} non trovato")
                if not web_tool.is_active:
                    raise HTTPException(
                        400, f"Il web tool '{web_tool.name}' non è attivo"
                    )

    if source_order:
        rows = (
            (await db.execute(select(Source).where(Source.project_id == project_id)))
            .scalars()
            .all()
        )
        by_id = {s.id: s for s in rows}
        for pos, sid in enumerate(source_order):
            if sid in by_id:
                by_id[sid].order_index = pos

    if mandatory_ids is not None:
        rows = (
            (await db.execute(select(Figure).where(Figure.project_id == project_id)))
            .scalars()
            .all()
        )
        wanted = set(mandatory_ids)
        for fig in rows:
            fig.mandatory = fig.id in wanted

    await db.commit()
    project = await _get_project_full(db, project_id)
    return project


@router.get("/projects/{project_key}/figures/{filename}")
async def get_figure(
    project_key: str, filename: str, db: AsyncSession = Depends(get_db)
):
    """Serve a figure image (extracted or user-uploaded) by filename."""
    project = await _project_by_key(db, project_key)
    safe = Path(filename).name
    path = settings.uploads_dir / f"project_{project.id}" / "figures" / safe
    if not path.exists():
        raise HTTPException(404, "Figura non trovata")
    return FileResponse(path, media_type="image/png")


@router.post("/projects/{project_key}/figures/upload")
async def upload_user_figure(
    project_key: str,
    file: UploadFile = File(...),
    caption: str = Form(""),
    target_section_title: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Upload a user-provided image and assign it to a target section.

    The image is stored in the project's ``figures`` directory alongside
    the extracted figures. A ``Figure`` record is created with
    ``user_uploaded=True``, so the pipeline can distinguish user images from
    PDF-extracted ones and place them in the specified section.
    """
    project = await _project_by_key(db, project_key)
    project_id = project.id

    # Validate the file is an image.
    fname = (file.filename or "image.png").lower()
    if not any(
        fname.endswith(ext)
        for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
    ):
        raise HTTPException(
            400, "Il file deve essere un'immagine (PNG, JPG, GIF, WEBP, BMP)"
        )

    # Store in the project's figures directory.
    figures_dir = settings.uploads_dir / f"project_{project_id}" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(fname).suffix or ".png"
    safe_name = f"user_{uuid.uuid4().hex[:12]}{ext}"
    target = figures_dir / safe_name
    content = await file.read()
    target.write_bytes(content)

    rel_path = f"figures/{safe_name}"

    # Get the next order_index among user-uploaded figures.
    existing_count = (
        (
            await db.execute(
                select(Figure).where(
                    Figure.project_id == project_id,
                    Figure.user_uploaded == True,  # noqa: E712
                )
            )
        )
        .scalars()
        .all()
    )
    next_order = len(existing_count) + 1

    figure = Figure(
        project_id=project_id,
        source_id=None,
        source_filename=None,
        rel_path=rel_path,
        page=0,
        mandatory=True,  # user-uploaded figures are always included
        order_index=next_order,
        caption=caption or None,
        custom_caption=caption or None,
        score=1.0,
        suggested=False,
        user_uploaded=True,
        target_section_title=target_section_title or None,
    )
    db.add(figure)
    await db.commit()
    await db.refresh(figure)
    return await _get_project_full(db, project_id)


@router.patch("/projects/{project_key}/figures/{figure_id}")
async def update_user_figure(
    project_key: str,
    figure_id: int,
    payload: FigureUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update the caption or target section of a user-uploaded figure."""
    project = await _project_by_key(db, project_key)
    figure = await db.get(Figure, figure_id)
    if figure is None or figure.project_id != project.id:
        raise HTTPException(404, "Figura non trovata")
    if not figure.user_uploaded:
        raise HTTPException(
            400, "Solo le figure caricate dall'utente possono essere modificate"
        )

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "Nessun campo da aggiornare")

    if "custom_caption" in updates:
        figure.custom_caption = updates["custom_caption"] or None
    if "target_section_title" in updates:
        figure.target_section_title = updates["target_section_title"] or None

    await db.commit()
    await db.refresh(figure)
    return await _get_project_full(db, project.id)


@router.delete("/projects/{project_key}/figures/{figure_id}")
async def delete_user_figure(
    project_key: str,
    figure_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a user-uploaded figure. Extracted figures cannot be deleted."""
    project = await _project_by_key(db, project_key)
    figure = await db.get(Figure, figure_id)
    if figure is None or figure.project_id != project.id:
        raise HTTPException(404, "Figura non trovata")
    if not figure.user_uploaded:
        raise HTTPException(
            400, "Solo le figure caricate dall'utente possono essere eliminate"
        )

    # Remove the file from disk.
    file_path = settings.uploads_dir / f"project_{project.id}" / figure.rel_path
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        pass

    await db.delete(figure)
    await db.commit()
    return await _get_project_full(db, project.id)


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects(db: AsyncSession = Depends(get_db)):
    rows = (
        (await db.execute(select(Project).order_by(Project.created_at.desc())))
        .scalars()
        .all()
    )
    return rows


@router.get("/projects/{project_key}", response_model=ProjectOut)
async def get_project(project_key: str, db: AsyncSession = Depends(get_db)):
    project = await _project_by_key(db, project_key)
    full = await _get_project_full(db, project.id)
    if full is None:
        raise HTTPException(404, "Progetto non trovato")
    return full


@router.delete("/projects/{project_key}")
async def delete_project(project_key: str, db: AsyncSession = Depends(get_db)):
    project = await _project_by_key(db, project_key)
    await db.delete(project)
    await db.commit()
    return {"ok": True}


@router.get("/projects/{project_key}/preview")
async def preview_latex(project_key: str, db: AsyncSession = Depends(get_db)):
    project = await _project_by_key(db, project_key)
    if not project.output_tex_path:
        raise HTTPException(404, "Documento non disponibile")
    path = Path(project.output_tex_path)
    if not path.exists():
        raise HTTPException(404, "File .tex mancante")
    return {"latex": path.read_text(encoding="utf-8")}


def _part_filename(section: Section, index: int) -> str:
    stem = slugify_title(section.title or "", fallback=f"part-{index:02d}")
    return f"parts/{index:02d}-{stem}.tex"


@router.get("/projects/{project_key}/files", response_model=list[ProjectFileOut])
async def list_files(project_key: str, db: AsyncSession = Depends(get_db)):
    """List the project's editable files: main.tex, each part, references.bib."""
    project = await _project_by_key(db, project_key)
    sections = await load_sections(db, project.id)

    main_content = project.main_tex_override or assemble_from_sections(
        project, sections
    )
    files: list[ProjectFileOut] = [
        ProjectFileOut(
            name="main.tex", kind="main", language="latex", content=main_content
        )
    ]
    for i, s in enumerate(sections, start=1):
        files.append(
            ProjectFileOut(
                name=_part_filename(s, i),
                kind="section",
                language="latex",
                content=s.latex or "",
                section_id=s.id,
            )
        )
    if project.bibliography_bib:
        files.append(
            ProjectFileOut(
                name="references.bib",
                kind="bib",
                language="bibtex",
                content=project.bibliography_bib,
            )
        )
    return files


@router.put("/projects/{project_key}/files")
async def save_file(
    project_key: str,
    payload: ProjectFileSave,
    db: AsyncSession = Depends(get_db),
):
    """Save an edited file and recompile the document.

    Editing ``main.tex`` stores a whole-document override compiled verbatim;
    editing a part or ``references.bib`` is a structured edit that clears any
    override and reassembles from the sections.
    """
    project = await _project_by_key(db, project_key)
    if payload.kind == "main":
        project.main_tex_override = payload.content
        result = await recompile_project(db, project, full_latex=payload.content)
    elif payload.kind == "section":
        if payload.section_id is None:
            raise HTTPException(400, "section_id mancante")
        section = await _resolve_section(db, project, payload.section_id)
        section.previous_latex = section.latex
        section.latex = payload.content
        project.main_tex_override = None
        result = await recompile_project(db, project)
    elif payload.kind == "bib":
        project.bibliography_bib = payload.content or None
        project.main_tex_override = None
        result = await recompile_project(db, project)
    else:
        raise HTTPException(400, "Tipo di file non valido")
    return {
        "success": result["success"],
        "pdf": result["success"],
        "log_excerpt": result["log_excerpt"],
    }


@router.post("/projects/{project_key}/sections/{section_id}/refine")
async def refine_section_endpoint(
    project_key: str,
    section_id: int,
    payload: SectionRefineRequest,
    db: AsyncSession = Depends(get_db),
):
    """Apply a quick fix instruction to one section and recompile the document."""
    if not payload.extra_prompt.strip():
        raise HTTPException(400, "Istruzione vuota")
    project = await _project_by_key(db, project_key)
    section = await db.get(Section, section_id)
    if section is None or section.project_id != project.id:
        raise HTTPException(404, "Sezione non trovata")
    provider = await db.get(ProviderConfig, payload.provider_id)
    if provider is None:
        raise HTTPException(404, "Provider non trovato")
    llm_config = build_llm_config(provider, payload.model)
    return await refine_section(db, project, section, payload.extra_prompt, llm_config)


async def _resolve_provider(db: AsyncSession, provider_id: int) -> ProviderConfig:
    provider = await db.get(ProviderConfig, provider_id)
    if provider is None:
        raise HTTPException(404, "Provider non trovato")
    return provider


async def _resolve_section(
    db: AsyncSession, project: Project, section_id: int
) -> Section:
    section = await db.get(Section, section_id)
    if section is None or section.project_id != project.id:
        raise HTTPException(404, "Sezione non trovata")
    return section


@router.post("/projects/{project_key}/recompile")
async def recompile_endpoint(
    project_key: str,
    payload: GenerateActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually retry compilation from the stored sections (LLM auto-fix loop).

    Recovers a run whose compilation failed after the automatic retries, without
    redoing analysis/planning/writing — the section work is preserved.
    """
    project = await _project_by_key(db, project_key)
    sections = (
        (await db.execute(select(Section).where(Section.project_id == project.id)))
        .scalars()
        .all()
    )
    if not sections:
        raise HTTPException(400, "Nessuna sezione da ricompilare")
    provider = await _resolve_provider(db, payload.provider_id)
    llm_config = build_llm_config(provider, payload.model)
    return await recompile_project(db, project, llm_config=llm_config, review_passes=2)


@router.post("/projects/{project_key}/rejudge")
async def rejudge_endpoint(
    project_key: str,
    payload: GenerateActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run the structural judge again on demand, applying a revision if needed."""
    project = await _project_by_key(db, project_key)
    provider = await _resolve_provider(db, payload.provider_id)
    llm_config = build_llm_config(provider, payload.model)
    return await rejudge_project(db, project, llm_config)


@router.post("/projects/{project_key}/sections/{section_id}/regenerate")
async def regenerate_section_endpoint(
    project_key: str,
    section_id: int,
    payload: GenerateActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Re-author one section from its source PDFs, then recompile the document."""
    project = await _project_by_key(db, project_key)
    section = await _resolve_section(db, project, section_id)
    provider = await _resolve_provider(db, payload.provider_id)
    llm_config = build_llm_config(provider, payload.model)
    return await regenerate_section(db, project, section, llm_config)


@router.post("/projects/{project_key}/sections/{section_id}/undo")
async def undo_section_endpoint(
    project_key: str,
    section_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Revert the last quick fix / regenerate of a section and recompile."""
    project = await _project_by_key(db, project_key)
    section = await _resolve_section(db, project, section_id)
    if not section.previous_latex:
        raise HTTPException(400, "Nessuna versione precedente da ripristinare")
    section.latex, section.previous_latex = section.previous_latex, section.latex
    result = await recompile_project(db, project)
    return {
        "success": result["success"],
        "section_id": section.id,
        "latex": section.latex,
        "log_excerpt": result["log_excerpt"],
        "can_undo": bool(section.previous_latex),
    }


@router.get("/projects/{project_key}/view/pdf")
async def view_pdf(project_key: str, db: AsyncSession = Depends(get_db)):
    """Serve the compiled PDF inline (for in-browser preview, not a download)."""
    project = await _project_by_key(db, project_key)
    if not project.output_pdf_path:
        raise HTTPException(404, "File non disponibile")
    path = Path(project.output_pdf_path)
    if not path.exists():
        raise HTTPException(404, "File mancante")
    return FileResponse(
        path,
        media_type="application/pdf",
        content_disposition_type="inline",
    )


@router.get("/projects/{project_key}/download/{kind}")
async def download(project_key: str, kind: str, db: AsyncSession = Depends(get_db)):
    project = await _project_by_key(db, project_key)
    slug = slugify_title(project.name)

    if kind == "pdf":
        if not project.output_pdf_path:
            raise HTTPException(404, "File non disponibile")
        path = Path(project.output_pdf_path)
        if not path.exists():
            raise HTTPException(404, "File mancante")
        return FileResponse(path, media_type="application/pdf", filename=f"{slug}.pdf")

    if kind == "tex":
        # The LaTeX download is a self-contained zip: main.tex + parts/ + figures.
        if not project.output_tex_path:
            raise HTTPException(404, "File non disponibile")
        main_path = Path(project.output_tex_path)
        if not main_path.exists():
            raise HTTPException(404, "File mancante")
        work_dir = main_path.parent
        full_latex = main_path.read_text(encoding="utf-8")
        main_tex, parts = split_into_part_files(full_latex)
        zip_path = work_dir / f"{slug}.zip"
        build_project_zip(
            zip_path,
            main_tex,
            parts,
            work_dir / "figures",
            bib_content=project.bibliography_bib,
        )
        return FileResponse(
            zip_path, media_type="application/zip", filename=f"{slug}.zip"
        )

    raise HTTPException(404, "Tipo di download non valido")


async def _get_project_full(db: AsyncSession, project_id: int) -> Project | None:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.sources),
            selectinload(Project.sections),
            selectinload(Project.figures),
        )
    )
    return result.scalar_one_or_none()
