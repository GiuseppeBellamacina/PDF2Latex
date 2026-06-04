"""Planner agent: merge analyses into a global document structure."""

from __future__ import annotations

import json
from typing import Any

from app.agents.prompts import PLANNER_SYSTEM
from app.agents.state import PlannedSection
from app.agents.utils import call_llm, parse_json_response


async def plan_document(
    analyses: list[dict[str, Any]],
    user_prompt: str,
    language: str,
    llm_config: dict[str, Any],
) -> tuple[str, list[PlannedSection]]:
    """Produce a document title and an ordered list of planned sections."""
    analyses_json = json.dumps(analyses, ensure_ascii=False, indent=2)
    prompt_part = (
        f"\n\nRichiesta personalizzata dell'utente:\n{user_prompt}"
        if user_prompt
        else ""
    )
    user = (
        f"Lingua del documento: {language}\n\n"
        f"Analisi dei documenti sorgente:\n{analyses_json}"
        f"{prompt_part}"
    )

    raw = await call_llm(llm_config, PLANNER_SYSTEM, user)
    data = parse_json_response(raw) or {}

    title = str(data.get("title") or "Documento Generato")
    raw_sections = data.get("sections", []) or []

    sections: list[PlannedSection] = []
    for idx, s in enumerate(raw_sections):
        sections.append(
            PlannedSection(
                part_title=str(s.get("part_title", "")),
                title=str(s.get("title", f"Sezione {idx + 1}")),
                order_index=int(s.get("order_index", idx)),
                outline=s.get("outline", {}) or {},
                source_filenames=list(s.get("source_filenames", []) or []),
            )
        )

    sections.sort(key=lambda s: s["order_index"])
    return title, sections
