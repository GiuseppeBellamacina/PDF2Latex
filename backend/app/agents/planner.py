"""Planner agent: merge analyses into a global document structure."""

from __future__ import annotations

import json
from typing import Any

from app.agents.prompts import PLANNER_SYSTEM
from app.agents.schemas import PlanSchema
from app.agents.state import PlannedSection
from app.agents.utils import call_llm_structured
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("planner")


async def plan_document(
    analyses: list[dict[str, Any]],
    user_prompt: str,
    language: str,
    llm_config: dict[str, Any],
    structure_hint: str = "",
) -> tuple[str, list[PlannedSection]]:
    """Produce a document title and an ordered list of planned sections."""
    analyses_json = json.dumps(analyses, ensure_ascii=False, indent=2)
    prompt_part = (
        f"\n\nRichiesta personalizzata dell'utente:\n{user_prompt}"
        if user_prompt
        else ""
    )
    structure_part = (
        f"\n\nIndicazioni su struttura/indice/ordine (da rispettare):\n{structure_hint}"
        if structure_hint
        else ""
    )
    user = (
        f"Lingua del documento: {language}\n\n"
        f"Analisi dei documenti sorgente (nell'ordine di elaborazione scelto):\n"
        f"{analyses_json}"
        f"{structure_part}"
        f"{prompt_part}"
    )

    plan_obj = await call_llm_structured(
        llm_config,
        PLANNER_SYSTEM,
        user,
        PlanSchema,
        temperature=settings.planner_temperature,
        label="plan",
    )

    title = plan_obj.title or "Documento Generato"
    sections: list[PlannedSection] = []
    for idx, s in enumerate(plan_obj.sections):
        sections.append(
            PlannedSection(
                part_title=s.part_title,
                title=s.title or f"Sezione {idx + 1}",
                order_index=int(s.order_index) if s.order_index is not None else idx,
                outline=s.outline or {},
                source_filenames=list(s.source_filenames or []),
            )
        )

    # ── Deterministic source-order sort ────────────────────────────────
    # When the user hasn't provided an explicit structure hint, sections
    # are sorted by the earliest source document they reference, so the
    # chapter order mirrors the extraction order the user chose.
    # Within the same source, the LLM's order_index is used as a tiebreak.
    source_order: dict[str, int] = {
        a.get("filename", ""): i for i, a in enumerate(analyses)
    }

    def _source_priority(s: PlannedSection) -> float:
        indices = [source_order[f] for f in s["source_filenames"] if f in source_order]
        return float(min(indices)) if indices else float("inf")

    if not structure_hint:
        sections.sort(key=lambda s: (_source_priority(s), s["order_index"]))
    else:
        sections.sort(key=lambda s: s["order_index"])

    # Rewrite order_index so the deterministic order is locked in for
    # downstream nodes (write_node, assembly).
    for i, s in enumerate(sections):
        s["order_index"] = i

    logger.info("Piano: '%s' con %d sezioni", title, len(sections))
    return title, sections
