"""REST API routes: providers, projects, upload, download."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
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
from app.services.refine import refine_section
from app.services.regenerate import regenerate_section
from app.services.rejudge import rejudge_project
from app.services.runner import build_llm_config

router = APIRouter()


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


# --------------------------- Projects -------------------------------------- #
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
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not files:
        raise HTTPException(400, "Nessun file caricato")

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
        status=ProjectStatus.uploaded,
        total_sources=len(files),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    dest_dir = settings.uploads_dir / f"project_{project.id}"
    figures_dir = dest_dir / "figures"
    dest_dir.mkdir(parents=True, exist_ok=True)

    fig_order = 0
    for idx, upload in enumerate(files):
        if not (upload.filename or "").lower().endswith(".pdf"):
            continue
        safe_name = Path(upload.filename).name
        target = dest_dir / safe_name
        content = await upload.read()
        target.write_bytes(content)
        source = Source(
            project_id=project.id,
            filename=safe_name,
            path=str(target),
            order_index=idx,
            n_pages=pdf_page_count(target),
        )
        db.add(source)
        await db.flush()  # get source.id

        # Extract embedded figures so the user can pick mandatory ones.
        try:
            figs = extract_figures(target, figures_dir)
        except Exception:  # noqa: BLE001 - figure extraction is best-effort
            figs = []
        for fig in figs:
            db.add(
                Figure(
                    project_id=project.id,
                    source_id=source.id,
                    source_filename=safe_name,
                    rel_path=fig.rel_path,
                    page=fig.page,
                    order_index=fig_order,
                    caption=fig.caption or None,
                    score=fig.score,
                    suggested=fig.suggested,
                    # Pre-select recommended figures; the user can adjust later.
                    mandatory=fig.suggested,
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

    for field, value in data.items():
        setattr(project, field, value)

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
    """Serve an extracted figure image by filename."""
    project = await _project_by_key(db, project_key)
    safe = Path(filename).name
    path = settings.uploads_dir / f"project_{project.id}" / "figures" / safe
    if not path.exists():
        raise HTTPException(404, "Figura non trovata")
    return FileResponse(path, media_type="image/png")


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
