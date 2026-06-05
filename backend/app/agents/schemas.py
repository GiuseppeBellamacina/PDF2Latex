"""Pydantic schemas used for structured LLM outputs.

Using explicit schemas (instead of free-form JSON we then regex-parse) lets us
validate the model's output, give the model a precise contract, and—on
providers that support it—use native structured output / function calling. The
helpers in :mod:`app.agents.utils` validate against these models and fall back
to lenient parsing when a provider cannot honour the schema (e.g. the offline
``fake`` model).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalysisSchema(BaseModel):
    """Structured analysis of a single source document (or chunk)."""

    summary: str = Field(default="", description="Riassunto di 3-5 frasi")
    topics: list[str] = Field(default_factory=list, description="Argomenti principali")
    formulas: list[str] = Field(
        default_factory=list, description="Formule/concetti matematici in LaTeX"
    )
    figures: list[str] = Field(
        default_factory=list, description="Figure/schemi/architetture descritte"
    )
    keywords: list[str] = Field(
        default_factory=list, description="Parole chiave per il recupero del contesto"
    )


class PlannedSectionSchema(BaseModel):
    part_title: str = Field(default="", description="Titolo della parte/capitolo")
    title: str = Field(default="", description="Titolo della sezione")
    order_index: int = Field(default=0)
    outline: dict = Field(default_factory=dict)
    source_filenames: list[str] = Field(default_factory=list)


class PlanSchema(BaseModel):
    """Structured global document plan."""

    title: str = Field(default="Documento Generato")
    sections: list[PlannedSectionSchema] = Field(default_factory=list)
