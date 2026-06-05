"""Reviewer agent: fix LaTeX compile errors and improve coherence."""

from __future__ import annotations

from typing import Any

from app.agents.prompts import REVIEWER_SYSTEM
from app.agents.utils import call_llm, strip_latex_fences
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("reviewer")

MAX_DOC_CHARS = 40000


async def review_document(
    full_latex: str,
    llm_config: dict[str, Any],
    compile_log: str | None = None,
) -> str:
    """Return a corrected full LaTeX document."""
    if compile_log:
        logger.info(
            "Reviewer: correzione su log di compilazione (%d caratteri doc)",
            len(full_latex),
        )
        user = (
            "Il seguente documento LaTeX non compila. "
            "Correggi gli errori segnalati dal log e restituisci il documento completo.\n\n"
            f"=== LOG DI ERRORE ===\n{compile_log[-3000:]}\n\n"
            f"=== DOCUMENTO ===\n{full_latex[:MAX_DOC_CHARS]}"
        )
    else:
        logger.info("Reviewer: revisione generale del documento")
        user = (
            "Rivedi e migliora il seguente documento LaTeX completo, "
            "correggendo eventuali errori e incoerenze.\n\n"
            f"{full_latex[:MAX_DOC_CHARS]}"
        )

    raw = await call_llm(
        llm_config,
        REVIEWER_SYSTEM,
        user,
        temperature=settings.reviewer_temperature,
        label="review",
    )
    return strip_latex_fences(raw)
