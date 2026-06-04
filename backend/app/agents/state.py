"""Shared state types for the LangGraph pipeline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]


class SourceAnalysis(TypedDict):
    filename: str
    summary: str
    topics: list[str]
    formulas: list[str]
    figures: list[str]


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


class GraphState(TypedDict, total=False):
    # Inputs
    user_prompt: str
    language: str
    documents: list[dict[str, Any]]  # serialized ExtractedDocument {filename, full_text, images}
    few_shot: str

    # LLM config (serialized LLMConfig dict)
    llm_config: dict[str, Any]

    # Paths
    work_dir: str
    figures_dir: str | None

    # Intermediate / outputs
    analyses: list[SourceAnalysis]
    title: str
    plan: list[PlannedSection]
    sections: list[WrittenSection]
    review_notes: list[str]
    final_latex: str
    pdf_path: str | None
    compile_log: str

    # Progress callback (not serialized, passed through)
    progress: ProgressCb
