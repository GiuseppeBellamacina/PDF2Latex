"""Composable OCR engines behind a single ``run_ocr`` interface.

Every engine takes the path to an image and returns recognised text. Engines are
loaded lazily and cached as module-level singletons (the heavy models are
expensive to build), and every import is guarded so a missing optional engine
never breaks extraction — it simply degrades to "no OCR" with a warning.

Supported engines (all local & free):

* ``tesseract``  — classic OCR via the system binary (``pytesseract``).
* ``rapidocr``   — ONNX multilingual OCR, no system binary.

The selected engine is chosen per project via the pipeline config; this module
only knows how to *run* a given engine id.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ocr")

# Lazily-built engine singletons (engine id -> object | None when unavailable).
_ENGINES: dict[str, object | None] = {}


def engine_available(engine: str) -> bool:
    """Whether the Python package backing ``engine`` is importable."""
    mod = {
        "tesseract": "pytesseract",
        "rapidocr": "rapidocr_onnxruntime",
    }.get(engine)
    if not mod:
        return False
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def best_available_ocr() -> str | None:
    """Return the best OCR engine actually installed (preference order)."""
    for engine in ("rapidocr", "tesseract"):
        if engine_available(engine):
            return engine
    return None


def _rapidocr(img_path: Path) -> str:
    eng = _ENGINES.get("rapidocr", "missing")
    if eng == "missing":
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            eng = RapidOCR()
        except Exception as exc:  # noqa: BLE001
            logger.warning("RapidOCR non inizializzabile: %s", exc)
            eng = None
        _ENGINES["rapidocr"] = eng
    if eng is None:
        return ""
    try:
        result, _ = eng(str(img_path))
        if not result:
            return ""
        return "\n".join(line[1] for line in result if len(line) > 1).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("RapidOCR fallito su %s: %s", img_path.name, exc)
        return ""


def _tesseract(img_path: Path, lang: str) -> str:
    # Reuse the resolved-binary logic in extractor to avoid duplication.
    from app.services.extractor import tesseract_available

    if not tesseract_available():
        return ""
    try:
        import pytesseract  # type: ignore
        from PIL import Image

        with Image.open(img_path) as im:
            return pytesseract.image_to_string(im, lang=lang).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tesseract fallito su %s: %s", img_path.name, exc)
        return ""


_RUNNERS = {
    "tesseract": lambda p, lang: _tesseract(p, lang),
    "rapidocr": lambda p, lang: _rapidocr(p),
}


def run_ocr(img_path: Path, lang: str | None = None, engine: str | None = None) -> str:
    """Run OCR on ``img_path`` with the chosen engine. Best-effort (never raises).

    Falls back to the best installed engine when the requested one is missing,
    and to nothing (``""``) when no OCR engine is available at all.
    """
    lang = lang or settings.ocr_lang
    engine = (engine or "tesseract").lower()
    if not engine_available(engine):
        fallback = best_available_ocr()
        if fallback and fallback != engine:
            logger.warning(
                "Motore OCR '%s' non disponibile: uso '%s'.", engine, fallback
            )
            engine = fallback
        else:
            logger.warning("Nessun motore OCR disponibile (richiesto '%s').", engine)
            return ""
    runner = _RUNNERS.get(engine)
    if runner is None:
        return ""
    return runner(Path(img_path), lang)
