"""Composable document-structure engines (rich markdown with tables).

A structure engine turns a whole PDF into structured markdown that captures
headings, paragraphs and — crucially — tables. The result is used as the primary
text for a document when present. Engines are import-guarded so a missing
optional engine degrades gracefully to "no structure" (the caller then falls
back to plain PyMuPDF text).

* ``docling``  — reuses the existing isolated, chunked, cached subprocess path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("structure")

ProgressCb = object  # imported lazily to avoid a cycle; treated as callable|None


def engine_available(engine: str) -> bool:
    mod = {
        "docling": "docling",
    }.get(engine)
    if not mod:
        return False
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def extract_structure(
    pdf_path: Path, engine: str = "docling", progress=None
) -> str | None:
    """Return rich markdown for ``pdf_path`` using ``engine`` (best-effort)."""
    engine = (engine or "docling").lower()
    if engine == "none":
        return None
    if engine == "docling":
        from app.services.extractor import docling_markdown_chunked

        return docling_markdown_chunked(pdf_path, progress)
    logger.warning("Motore struttura sconosciuto: %s", engine)
    return None
