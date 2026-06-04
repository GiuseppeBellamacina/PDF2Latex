"""Writer agent: write the LaTeX body of a single section (fan-out)."""

from __future__ import annotations

import json
from typing import Any

from app.agents.prompts import WRITER_SYSTEM
from app.agents.state import PlannedSection, WrittenSection
from app.agents.utils import call_llm, strip_latex_fences

MAX_SOURCE_CHARS = 12000
MAX_FEWSHOT_CHARS = 6000


async def write_section(
    section: PlannedSection,
    documents_by_name: dict[str, str],
    few_shot: str,
    language: str,
    llm_config: dict[str, Any],
) -> WrittenSection:
    """Generate the LaTeX body for one planned section."""
    outline_json = json.dumps(section["outline"], ensure_ascii=False, indent=2)

    source_text = ""
    for fname in section["source_filenames"]:
        chunk = documents_by_name.get(fname, "")
        if chunk:
            source_text += f"\n--- {fname} ---\n{chunk[:MAX_SOURCE_CHARS]}\n"

    fewshot_part = (
        f"\n\nEsempio di stile LaTeX desiderato:\n{few_shot[:MAX_FEWSHOT_CHARS]}"
        if few_shot
        else ""
    )

    user = (
        f"Lingua: {language}\n"
        f"Parte: {section['part_title']}\n"
        f"Titolo sezione: {section['title']}\n\n"
        f"Outline:\n{outline_json}\n\n"
        f"Materiale sorgente:\n{source_text}"
        f"{fewshot_part}"
    )

    raw = await call_llm(llm_config, WRITER_SYSTEM, user)
    latex = strip_latex_fences(raw)

    return WrittenSection(
        title=section["title"],
        part_title=section["part_title"],
        order_index=section["order_index"],
        latex=latex,
    )
