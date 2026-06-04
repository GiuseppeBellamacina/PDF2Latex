"""Analyzer agent: analyze a single source document (fan-out)."""

from __future__ import annotations

from typing import Any

from app.agents.prompts import ANALYZER_SYSTEM
from app.agents.state import SourceAnalysis
from app.agents.utils import call_llm, parse_json_response

MAX_CHARS = 24000


async def analyze_document(
    document: dict[str, Any], llm_config: dict[str, Any]
) -> SourceAnalysis:
    """Analyze one extracted document into a structured outline."""
    filename = document["filename"]
    text = document.get("full_text", "")[:MAX_CHARS]

    user = f"Documento: {filename}\n\nContenuto estratto:\n{text}"
    raw = await call_llm(llm_config, ANALYZER_SYSTEM, user)
    data = parse_json_response(raw) or {}

    return SourceAnalysis(
        filename=filename,
        summary=str(data.get("summary", "")),
        topics=list(data.get("topics", []) or []),
        formulas=list(data.get("formulas", []) or []),
        figures=list(data.get("figures", []) or []),
    )
