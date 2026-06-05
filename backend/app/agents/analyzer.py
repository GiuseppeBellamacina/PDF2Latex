"""Analyzer agent: analyze a single source document (fan-out).

Long documents are processed with a map-reduce strategy: the text is split into
chunks that fit comfortably in the model's context, each chunk is analyzed in
parallel (map), and the partial analyses are merged—with a short synthesis
call for the summary—into one coherent :class:`SourceAnalysis` (reduce). This
removes the silent truncation that previously discarded everything past a fixed
character cut-off.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.prompts import ANALYZER_REDUCE_SYSTEM, ANALYZER_SYSTEM
from app.agents.schemas import AnalysisSchema
from app.agents.state import SourceAnalysis
from app.agents.utils import call_llm, call_llm_structured
from app.core.config import settings
from app.core.logging import get_logger
from app.services.text_cleaning import split_into_chunks

logger = get_logger("analyzer")


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        key = it.strip().lower()
        if it.strip() and key not in seen:
            seen.add(key)
            out.append(it.strip())
    return out


async def _analyze_chunk(
    filename: str, idx: int, total: int, text: str, llm_config: dict[str, Any]
) -> AnalysisSchema:
    header = (
        f"Documento: {filename} (parte {idx}/{total})"
        if total > 1
        else f"Documento: {filename}"
    )
    user = f"{header}\n\nContenuto estratto:\n{text}"
    return await call_llm_structured(
        llm_config,
        ANALYZER_SYSTEM,
        user,
        AnalysisSchema,
        temperature=settings.analyzer_temperature,
        label=f"analyze:{filename}#{idx}",
    )


async def analyze_document(
    document: dict[str, Any], llm_config: dict[str, Any]
) -> SourceAnalysis:
    """Analyze one extracted document into a structured outline (map-reduce)."""
    filename = document["filename"]
    text = document.get("full_text", "")

    chunks = split_into_chunks(text, settings.analyzer_chunk_chars)
    if len(chunks) > settings.analyzer_max_chunks:
        logger.warning(
            "%s: %d chunk oltre il limite %d, troncamento ai primi",
            filename,
            len(chunks),
            settings.analyzer_max_chunks,
        )
        chunks = chunks[: settings.analyzer_max_chunks]
    if not chunks:
        chunks = [""]

    logger.info("Analisi %s: %d chunk", filename, len(chunks))

    total = len(chunks)
    partials: list[AnalysisSchema] = await asyncio.gather(
        *[
            _analyze_chunk(filename, i + 1, total, ch, llm_config)
            for i, ch in enumerate(chunks)
        ]
    )

    # Reduce: merge structured fields, dedup.
    topics = _dedup_keep_order([t for p in partials for t in p.topics])
    formulas = _dedup_keep_order([f for p in partials for f in p.formulas])
    figures = _dedup_keep_order([f for p in partials for f in p.figures])
    keywords = _dedup_keep_order([k for p in partials for k in p.keywords])

    summaries = [p.summary for p in partials if p.summary.strip()]
    if len(summaries) == 1:
        summary = summaries[0]
    elif summaries:
        # Synthesize a single coherent summary from the chunk summaries.
        joined = "\n".join(f"- {s}" for s in summaries)
        summary = await call_llm(
            llm_config,
            ANALYZER_REDUCE_SYSTEM,
            f"Documento: {filename}\n\nRiassunti parziali:\n{joined}",
            temperature=settings.analyzer_temperature,
            label=f"analyze-reduce:{filename}",
        )
        summary = summary.strip()
    else:
        summary = ""

    logger.info(
        "Analisi %s completata: %d argomenti, %d formule, %d figure",
        filename,
        len(topics),
        len(formulas),
        len(figures),
    )

    return SourceAnalysis(
        filename=filename,
        summary=summary,
        topics=topics,
        formulas=formulas,
        figures=figures,
        keywords=keywords,
    )
