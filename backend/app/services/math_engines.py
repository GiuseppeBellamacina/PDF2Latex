"""Composable math/equation recovery engines.

These engines recover formulas as LaTeX. They are optional and import-guarded; a
missing engine simply means no extra math recovery (the document still builds).

* ``pix2tex`` — single-equation image -> LaTeX (LaTeX-OCR). GPU-friendly.

Both run locally and free.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("math")

_MODELS: dict[str, object | None] = {}


def engine_available(engine: str) -> bool:
    mod = {"pix2tex": "pix2tex"}.get(engine)
    if not mod:
        return False
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def equation_to_latex(img_path: Path, engine: str = "pix2tex") -> str:
    """Convert the image of a single equation to LaTeX (best-effort)."""
    engine = (engine or "none").lower()
    if engine != "pix2tex":
        return ""
    model = _MODELS.get("pix2tex", "missing")
    if model == "missing":
        try:
            from pix2tex.cli import LatexOCR  # type: ignore

            model = LatexOCR()
        except Exception as exc:  # noqa: BLE001
            logger.warning("pix2tex non inizializzabile: %s", exc)
            model = None
        _MODELS["pix2tex"] = model
    if model is None:
        return ""
    try:
        from PIL import Image

        with Image.open(img_path) as im:
            return str(model(im)).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("pix2tex fallito su %s: %s", img_path.name, exc)
        return ""
