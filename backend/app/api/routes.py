"""REST API routes: providers, projects, upload, download."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    ProjectOut,
    ProjectSummary,
    ProjectUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderTestRequest,
    ProviderUpdate,
)
from app.core.config import settings
from app.core.encryption import encrypt_api_key
from app.core.llm_factory import LLMConfig, test_llm_connection
from app.db.database import get_db
from app.db.models import Figure, Project, ProjectStatus, ProviderConfig, Source
from app.services.extractor import available_backends, extract_figures

router = APIRouter()


@router.get("/backends")
async def list_backends():
    """Report which extractor backends are installed/usable."""
    return available_backends()


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


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Progetto non trovato")

    data = payload.model_dump(exclude_unset=True)
    source_order = data.pop("source_order", None)
    mandatory_ids = data.pop("mandatory_figure_ids", None)

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


@router.get("/projects/{project_id}/figures/{filename}")
async def get_figure(project_id: int, filename: str):
    """Serve an extracted figure image by filename."""
    safe = Path(filename).name
    path = settings.uploads_dir / f"project_{project_id}" / "figures" / safe
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


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await _get_project_full(db, project_id)
    if project is None:
        raise HTTPException(404, "Progetto non trovato")
    return project


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Progetto non trovato")
    await db.delete(project)
    await db.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/preview")
async def preview_latex(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if project is None or not project.output_tex_path:
        raise HTTPException(404, "Documento non disponibile")
    path = Path(project.output_tex_path)
    if not path.exists():
        raise HTTPException(404, "File .tex mancante")
    return {"latex": path.read_text(encoding="utf-8")}


@router.get("/projects/{project_id}/download/{kind}")
async def download(project_id: int, kind: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Progetto non trovato")
    path_str = project.output_tex_path if kind == "tex" else project.output_pdf_path
    if not path_str:
        raise HTTPException(404, "File non disponibile")
    path = Path(path_str)
    if not path.exists():
        raise HTTPException(404, "File mancante")
    media = "application/pdf" if kind == "pdf" else "application/x-tex"
    return FileResponse(path, media_type=media, filename=path.name)


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
