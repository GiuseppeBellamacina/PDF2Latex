"""LLM-based figure scoring: re-evaluate extracted figures using a vision model.

When the pipeline's ``figure_scoring`` stage is set to ``vlm``, this module
re-scores every extracted figure by sending its image (base64) together with
the text that surrounded it on its source page to a vision-capable LLM. The
heuristic score is kept as a fallback; the LLM score overwrites it when the
call succeeds.

The scoring runs at generation time (inside the runner), *after* extraction
but *before* the pipeline, so the LLM provider is already selected.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from app.agents.utils import call_llm
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("figure_scorer")

# Lazy-init semaphore keyed by running event loop + concurrency value
# (avoids the pytest-asyncio "bound to different event loop" RuntimeError
# and correctly responds to per-call concurrency overrides).
_SEMAPHORE_STATE: dict[str, Any] = {"loop": None, "sem": None, "concurrency": None}


def _get_semaphore(concurrency: int | None = None) -> asyncio.Semaphore:
    limit = concurrency or settings.llm_max_concurrency
    loop = asyncio.get_running_loop()
    if _SEMAPHORE_STATE["loop"] is not loop or _SEMAPHORE_STATE["concurrency"] != limit:
        _SEMAPHORE_STATE["loop"] = loop
        _SEMAPHORE_STATE["concurrency"] = limit
        _SEMAPHORE_STATE["sem"] = asyncio.Semaphore(limit)
    return _SEMAPHORE_STATE["sem"]


_SCORE_FIGURE_SYSTEM = """Sei un revisore accademico che valuta se un'immagine estratta da un PDF
merita di essere inclusa in un documento LaTeX riassuntivo.

Per ogni immagine ricevi:
- L'immagine stessa (codificata in base64)
- Il testo circostante nella pagina originale (fino a 1500 caratteri)

Assegna un punteggio da 0.0 a 1.0 dove:
- 0.0 = decorativa / irrilevante / logo / banner / spazio vuoto
- 0.3 = marginale (es. icona, screenshot di UI, foto stock)
- 0.6 = utile (grafico semplice, tabella, schema chiaro)
- 0.9 = essenziale (diagramma chiave, architettura, risultato sperimentale)

Rispondi SOLO con un numero decimale tra 0.0 e 1.0. Nessun'altra spiegazione."""


async def score_one_figure(
    rel_path: str,
    context_text: str,
    figures_dir: Path,
    llm_config: dict[str, Any],
) -> float:
    """Score a single figure image with an LLM using its page context.

    Returns a score 0.0–1.0, or the heuristic score unchanged on failure.
    """
    img_path = figures_dir / Path(rel_path).name
    if not img_path.exists():
        logger.debug("Figura non trovata per LLM scoring: %s", img_path)
        return -1.0  # caller should keep heuristic score

    try:
        img_bytes = img_path.read_bytes()
        img_b64 = base64.b64encode(img_bytes).decode("ascii")
    except OSError as exc:
        logger.debug("Impossibile leggere figura %s: %s", rel_path, exc)
        return -1.0

    # Build a simple data-URI for the image (PNG assumed).
    image_part = f"data:image/png;base64,{img_b64}"
    context = context_text[:1500] if context_text else "(nessun contesto disponibile)"

    user_message = (
        f"Immagine:\\n{image_part}\\n\\n"
        f"Testo circostante nella pagina originale:\\n{context}\\n\\n"
        f"Valuta la rilevanza di questa immagine (0.0-1.0):"
    )

    try:
        raw = await call_llm(
            llm_config,
            _SCORE_FIGURE_SYSTEM,
            user_message,
            temperature=0.0,
            label=f"figure-score:{Path(rel_path).stem}",
        )
        # Parse the response: extract the first float-like token.
        import re

        match = re.search(r"([01]?(?:\.\d+)?)", raw.strip())
        if match and match.group(1):
            score = float(match.group(1))
            return round(max(0.0, min(score, 1.0)), 3)
        logger.debug("LLM figure score non parsabile: %s", raw[:80])
        return -1.0
    except Exception as exc:
        logger.debug("LLM figure scoring fallito per %s: %s", rel_path, exc)
        return -1.0


async def score_figures_with_llm(
    figures: list[dict[str, Any]],
    figures_dir: Path,
    llm_config: dict[str, Any],
    concurrency: int | None = None,
) -> list[dict[str, Any]]:
    """Re-score a batch of figures using LLM vision + page context.

    Each figure dict should have ``rel_path``, ``context_text``, and ``score``
    (the existing heuristic score). The LLM score replaces ``score`` when the
    call returns a valid number. Runs up to ``concurrency`` calls in parallel.

    Returns the updated list (mutated in place, but also returned for clarity).
    """
    sem = _get_semaphore(concurrency)

    async def _score_one(fig: dict[str, Any]) -> None:
        async with sem:
            llm_score = await score_one_figure(
                fig.get("rel_path", ""),
                fig.get("context_text", ""),
                figures_dir,
                llm_config,
            )
            if llm_score >= 0.0:
                old = fig.get("score", 0.0)
                fig["score"] = llm_score
                fig["suggested"] = llm_score >= 0.52
                logger.debug(
                    "Figura %s: heuristic=%.3f → llm=%.3f",
                    fig.get("rel_path", "?"),
                    old,
                    llm_score,
                )

    tasks = [_score_one(f) for f in figures]
    await asyncio.gather(*tasks)
    logger.info("LLM figure scoring completato su %d figure", len(figures))
    return figures
