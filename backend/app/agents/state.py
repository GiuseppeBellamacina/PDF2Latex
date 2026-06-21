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
    # Per-role LLM overrides: {role_name: serialized_LLMConfig}. When a role
    # has a config here, that role uses it; otherwise falls back to llm_config.
    role_configs: dict[str, dict[str, Any]]

    # Per-run overrides (decided in the UI, not from global settings)
    judge_vision: bool
    writer_use_knowledge: bool

    # Research mode (web-based research, no PDFs required)
    research_mode: bool
    web_tool_configs: list[dict[str, Any]]  # serialized WebToolConfig list for search

    # Paths
    work_dir: str
    figures_dir: str | None

    # Intermediate / outputs — doc_analyses + web_analyses are merged into
    # ``analyses`` before planning, so downstream nodes are agnostic.
    doc_analyses: Required[list[SourceAnalysis]]
    web_analyses: Required[list[SourceAnalysis]]
    analyses: Required[list[SourceAnalysis]]
    title: str
    plan: Required[list[PlannedSection]]
    sections: Required[list[WrittenSection]]
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

    # Per-chapter list of established facts (extracted after each section,
    # passed as progressive context to subsequent sections in the same chapter).
    established_facts: dict[str, list[str]]

    # Coherence checker: validates cross-chapter scientific consistency.
    # ``coherence_issues`` lists contradictions or terminology mismatches found
    # across chapters; ``coherence_score`` is an overall 0-100 rating.
    coherence_issues: list[str]
    coherence_score: int

    # Citation auditor: verifies source references are properly used.
    # ``citation_issues`` flags uncited user sources, unknown keys, or missed
    # references; ``citation_report`` is a human-readable summary.
    citation_issues: list[str]
    citation_report: str

    # User-provided bibliographic sources (structured references the user wants
    # the system to cite and optionally enrich the content with). Merged into
    # the references pool before writing.
    user_sources: list[dict[str, str]]

    # Progress callback (not serialized, passed through)
    progress: ProgressCb
