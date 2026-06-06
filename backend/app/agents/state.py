"""Shared state types for the LangGraph pipeline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Required, TypedDict

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]


class SourceAnalysis(TypedDict):
    filename: str
    summary: str
    topics: list[str]
    formulas: list[str]
    figures: list[str]
    keywords: list[str]
    references: list[dict[str, str]]


class PlannedSection(TypedDict):
    part_title: str
    title: str
    order_index: int
    outline: dict[str, Any]
    source_filenames: list[str]


class WrittenSection(TypedDict):
    title: str
    part_title: str
    order_index: int
    latex: str
    outline: dict[str, Any]
    source_filenames: list[str]


class GraphState(TypedDict, total=False):
    # ``Required`` marks the keys always present by the time they are read via
    # subscript (the pipeline inputs, and the intermediates produced by an
    # earlier node before any node that reads them). The rest stay optional and
    # are accessed with ``state.get(...)``.
    # Inputs
    user_prompt: str
    language: str
    documents: Required[
        list[dict[str, Any]]
    ]  # serialized ExtractedDocument {filename, full_text, figures}
    few_shot: str
    metadata: dict[str, Any]  # title/author/subtitle/abstract/cover_date
    structure_hint: str

    # LLM config (serialized LLMConfig dict)
    llm_config: Required[dict[str, Any]]

    # Per-run overrides (decided in the UI, not from global settings)
    judge_vision: bool

    # Paths
    work_dir: str
    figures_dir: str | None

    # Intermediate / outputs
    analyses: Required[list[SourceAnalysis]]
    title: str
    plan: Required[list[PlannedSection]]
    sections: Required[list[WrittenSection]]
    review_notes: list[str]
    overview_latex: str  # optional per-chapter synopsis block (TOC-like)
    # Bibliography: ``references_pool`` is every reference extracted from the
    # sources (with citation keys); ``bibliography_bib`` is the BibTeX database
    # filtered to the entries actually cited in the final document.
    references_pool: list[dict[str, str]]
    bibliography_bib: str
    final_latex: Required[str]
    pdf_path: str | None
    compile_log: str

    # Judge stage: structural verdict + revision bookkeeping
    judge_rounds: int
    judge_action: str  # "approve" | "revise" | "skip" | "stop"
    judge_score: int
    good_latex: Required[str]  # last version that compiled (rollback target)
    good_pdf: Required[str | None]

    # Progress callback (not serialized, passed through)
    progress: ProgressCb
