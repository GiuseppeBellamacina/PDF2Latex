"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------- Providers ------------------------------------- #
class ProviderCreate(BaseModel):
    name: str
    provider_type: str
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    params: dict[str, Any] | None = None
    is_active: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    params: dict[str, Any] | None = None
    is_active: bool | None = None


class ProviderOut(BaseModel):
    id: int
    name: str
    provider_type: str
    base_url: str | None
    default_model: str | None
    params: dict[str, Any] | None
    is_active: bool
    has_api_key: bool

    class Config:
        from_attributes = True


class ProviderTestRequest(BaseModel):
    provider_type: str
    model: str
    api_key: str | None = None
    base_url: str | None = None


# --------------------------- Projects -------------------------------------- #
class SourceOut(BaseModel):
    id: int
    filename: str
    n_pages: int
    order_index: int

    class Config:
        from_attributes = True


class FigureOut(BaseModel):
    id: int
    source_filename: str | None
    rel_path: str
    page: int
    mandatory: bool
    order_index: int
    caption: str | None = None
    score: float | None = None
    suggested: bool | None = None

    class Config:
        from_attributes = True


class SectionOut(BaseModel):
    id: int
    part_title: str | None
    title: str
    order_index: int
    status: str
    latex: str | None
    has_undo: bool = False
    has_source: bool = False

    class Config:
        from_attributes = True


class SectionRefineRequest(BaseModel):
    """A quick post-generation fix instruction for a single section."""

    provider_id: int
    model: str | None = None
    extra_prompt: str


class GenerateActionRequest(BaseModel):
    """Provider selection for an on-demand action (recompile/rejudge/regenerate)."""

    provider_id: int
    model: str | None = None


class ProjectFileOut(BaseModel):
    """One editable file of the project (main.tex, a chapter part, references.bib)."""

    name: str
    kind: str  # "main" | "section" | "bib"
    language: str  # editor syntax mode: "latex" | "bibtex"
    content: str
    section_id: int | None = None


class ProjectFileSave(BaseModel):
    """Save the edited content of one project file and recompile."""

    kind: str  # "main" | "section" | "bib"
    section_id: int | None = None
    content: str


class ProjectUpdate(BaseModel):
    """Editable project configuration set on the configuration page."""

    name: str | None = None
    user_prompt: str | None = None
    language: str | None = None
    author: str | None = None
    subtitle: str | None = None
    abstract: str | None = None
    cover_date: str | None = None
    structure_hint: str | None = None
    extractor_backend: str | None = None
    enable_ocr: bool | None = None
    judge_vision: bool | None = None
    # Ordered list of source ids -> sets order_index
    source_order: list[int] | None = None
    # Ids of figures to force-include
    mandatory_figure_ids: list[int] | None = None


class ProjectOut(BaseModel):
    # ``id`` is the opaque public identifier (read from the ORM ``public_id``),
    # so the sequential integer primary key is never exposed in the API/URLs.
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(validation_alias="public_id")
    name: str
    user_prompt: str | None
    language: str
    status: str
    author: str | None = None
    subtitle: str | None = None
    abstract: str | None = None
    cover_date: str | None = None
    structure_hint: str | None = None
    extractor_backend: str | None = None
    enable_ocr: bool | None = None
    judge_vision: bool | None = None
    output_tex_path: str | None
    output_pdf_path: str | None
    error_message: str | None
    total_sources: int
    total_sections: int
    completed_sections: int
    created_at: datetime
    sources: list[SourceOut] = []
    sections: list[SectionOut] = []
    figures: list[FigureOut] = []


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(validation_alias="public_id")
    name: str
    status: str
    language: str
    total_sources: int
    created_at: datetime
