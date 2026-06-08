"""Composable document-structure engines (rich markdown with tables).

A structure engine turns a whole PDF into structured markdown that captures
headings, paragraphs and — crucially — tables. The result is used as the primary
text for a document when present. Engines are import-guarded so a missing
optional engine degrades gracefully to "no structure" (the caller then falls
back to plain PyMuPDF text).

* ``docling``  — reuses the existing isolated, chunked, cached subprocess path.
* ``marker``   — PDF→markdown via the Marker converter (GPU-friendly).
* ``mineru``   — MinerU document-understanding pipeline (GPU-friendly).
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
        "marker": "marker",
        "mineru": "magic_pdf",
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
    if engine == "marker":
        return _marker(pdf_path)
    if engine == "mineru":
        return _mineru(pdf_path)
    logger.warning("Motore struttura sconosciuto: %s", engine)
    return None


def _marker(pdf_path: Path) -> str | None:
    try:
        from marker.converters.pdf import PdfConverter  # type: ignore
        from marker.models import create_model_dict  # type: ignore
        from marker.output import text_from_rendered  # type: ignore

        converter = PdfConverter(artifact_dict=create_model_dict())
        rendered = converter(str(pdf_path))
        text, _, _ = text_from_rendered(rendered)
        return (text or "").strip() or None
    except Exception as exc:  # noqa: BLE001 - optional engine, best-effort
        logger.warning("Marker non disponibile/fallito: %s", exc)
        return None


def _mineru(pdf_path: Path) -> str | None:
    try:
        from magic_pdf.data.data_reader_writer import (  # type: ignore
            FileBasedDataReader,
        )
        from magic_pdf.data.dataset import PymuDocDataset  # type: ignore
        from magic_pdf.model.doc_analyze_by_custom_model import (  # type: ignore
            doc_analyze,
        )

        reader = FileBasedDataReader("")
        pdf_bytes = reader.read(str(pdf_path))
        dataset = PymuDocDataset(pdf_bytes)
        inference = dataset.apply(doc_analyze, ocr=True)
        pipe = inference.pipe_ocr_mode(None)
        md = pipe.get_markdown("")
        return (md or "").strip() or None
    except Exception as exc:  # noqa: BLE001 - optional engine, best-effort
        logger.warning("MinerU non disponibile/fallito: %s", exc)
        return None
