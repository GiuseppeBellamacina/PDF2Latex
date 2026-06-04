"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


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

    class Config:
        from_attributes = True


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
    # Ordered list of source ids -> sets order_index
    source_order: list[int] | None = None
    # Ids of figures to force-include
    mandatory_figure_ids: list[int] | None = None


class ProjectOut(BaseModel):
    id: int
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

    class Config:
        from_attributes = True


class ProjectSummary(BaseModel):
    id: int
    name: str
    status: str
    language: str
    total_sources: int
    created_at: datetime

    class Config:
        from_attributes = True
