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


class ReferenceSchema(BaseModel):
    """A single bibliographic reference parsed from a source document."""

    authors: str = Field(default="", description="Autori (cognomi separati da 'and')")
    title: str = Field(default="", description="Titolo dell'opera citata")
    year: str = Field(default="", description="Anno di pubblicazione")
    venue: str = Field(
        default="", description="Rivista/conferenza/editore, se disponibile"
    )


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
    references: list[ReferenceSchema] = Field(
        default_factory=list,
        description="Riferimenti bibliografici realmente presenti nel documento",
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


class ChapterSynopsisSchema(BaseModel):
    """A 2-3 sentence synopsis of a single chapter for the overview page."""

    part_title: str = Field(default="", description="Titolo del capitolo")
    synopsis: str = Field(default="", description="Sintesi di 2-3 frasi del capitolo")


class OverviewSchema(BaseModel):
    """Per-chapter synopses used to build the document's overview page."""

    chapters: list[ChapterSynopsisSchema] = Field(default_factory=list)


class JudgeSchema(BaseModel):
    """Structural verdict on the assembled document produced by the judge."""

    approved: bool = Field(
        default=True,
        description="True se la struttura complessiva è adeguata e non servono modifiche",
    )
    score: int = Field(
        default=0, description="Qualità strutturale complessiva da 0 a 100"
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Problemi strutturali concreti da correggere (vuoto se approvato)",
    )
    summary: str = Field(
        default="", description="Breve giudizio sulla struttura del documento"
    )


class CoherenceSchema(BaseModel):
    """Cross-chapter coherence verdict from the coherence checker."""

    approved: bool = Field(
        default=True,
        description="True se non ci sono contraddizioni o incoerenze tra capitoli",
    )
    score: int = Field(
        default=0, description="Coerenza scientifica complessiva da 0 a 100"
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Contraddizioni, incoerenze o ripetizioni sostanziali (vuoto se ok)",
    )
    summary: str = Field(
        default="", description="Breve giudizio sulla coerenza tra capitoli"
    )


class CitationAuditSchema(BaseModel):
    """Citation audit verdict from the citation auditor."""

    approved: bool = Field(
        default=True,
        description="True se tutte le fonti sono correttamente citate",
    )
    score: int = Field(default=0, description="Qualità delle citazioni da 0 a 100")
    uncited_user_sources: list[str] = Field(
        default_factory=list,
        description="Chiavi delle fonti utente NON citate nel documento",
    )
    unknown_citations: list[str] = Field(
        default_factory=list,
        description="Chiavi citate con \\cite ma NON presenti nel pool",
    )
    missed_source_refs: list[str] = Field(
        default_factory=list,
        description="Chiavi di riferimenti estratti dai PDF che il documento avrebbe dovuto citare",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Problemi con le citazioni (vuoto se ok)",
    )
    summary: str = Field(default="", description="Breve riepilogo dell'audit citazioni")
