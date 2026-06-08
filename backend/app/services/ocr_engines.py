"""Composable OCR engines behind a single ``run_ocr`` interface.

Every engine takes the path to an image and returns recognised text. Engines are
loaded lazily and cached as module-level singletons (the heavy models are
expensive to build), and every import is guarded so a missing optional engine
never breaks extraction — it simply degrades to "no OCR" with a warning.

Supported engines (all local & free):

* ``tesseract``  — classic OCR via the system binary (``pytesseract``).
* ``rapidocr``   — ONNX multilingual OCR, no system binary.
* ``paddleocr``  — accurate OCR with layout detection (GPU-friendly).
* ``surya``      — transformer OCR for hard layouts (GPU).
* ``dots_ocr``   — compact VLM doing OCR + layout (GPU).

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
        "paddleocr": "paddleocr",
        "surya": "surya",
        "dots_ocr": "transformers",
    }.get(engine)
    if not mod:
        return False
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def best_available_ocr() -> str | None:
    """Return the best OCR engine actually installed (preference order)."""
    for engine in ("paddleocr", "rapidocr", "surya", "tesseract"):
        if engine_available(engine):
            return engine
    return None


# --------------------------------------------------------------------------- #
# Per-engine runners                                                            #
# --------------------------------------------------------------------------- #


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


def _paddleocr(img_path: Path, lang: str) -> str:
    eng = _ENGINES.get("paddleocr", "missing")
    if eng == "missing":
        try:
            from paddleocr import PaddleOCR  # type: ignore

            eng = PaddleOCR(use_angle_cls=True, lang=_paddle_lang(lang), show_log=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PaddleOCR non inizializzabile: %s", exc)
            eng = None
        _ENGINES["paddleocr"] = eng
    if eng is None:
        return ""
    try:
        result = eng.ocr(str(img_path), cls=True)
        lines: list[str] = []
        for page in result or []:
            for entry in page or []:
                if len(entry) > 1 and entry[1]:
                    lines.append(str(entry[1][0]))
        return "\n".join(lines).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("PaddleOCR fallito su %s: %s", img_path.name, exc)
        return ""


def _paddle_lang(lang: str) -> str:
    """Map a tesseract-style language string to a PaddleOCR language code."""
    first = lang.split("+")[0].strip().lower()
    return {
        "ita": "it",
        "eng": "en",
        "fra": "fr",
        "deu": "german",
        "spa": "es",
        "por": "pt",
    }.get(first, "en")


def _surya(img_path: Path, lang: str) -> str:
    eng = _ENGINES.get("surya", "missing")
    if eng == "missing":
        try:
            from surya.model.detection.model import (  # type: ignore
                load_model as load_det,
            )
            from surya.model.detection.model import (
                load_processor as load_det_proc,
            )
            from surya.model.recognition.model import (  # type: ignore
                load_model as load_rec,
            )
            from surya.model.recognition.processor import (  # type: ignore
                load_processor as load_rec_proc,
            )

            eng = {
                "det_model": load_det(),
                "det_proc": load_det_proc(),
                "rec_model": load_rec(),
                "rec_proc": load_rec_proc(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Surya non inizializzabile: %s", exc)
            eng = None
        _ENGINES["surya"] = eng
    if eng is None:
        return ""
    try:
        from PIL import Image
        from surya.ocr import run_ocr as surya_run  # type: ignore

        with Image.open(img_path) as im:
            image = im.convert("RGB")
        langs = [c.strip() for c in lang.split("+") if c.strip()] or ["en"]
        preds = surya_run(
            [image],
            [langs],
            eng["det_model"],
            eng["det_proc"],
            eng["rec_model"],
            eng["rec_proc"],
        )
        if not preds:
            return ""
        return "\n".join(line.text for line in preds[0].text_lines if line.text).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Surya fallito su %s: %s", img_path.name, exc)
        return ""


def _dots_ocr(img_path: Path) -> str:
    eng = _ENGINES.get("dots_ocr", "missing")
    if eng == "missing":
        try:
            from transformers import AutoModelForCausalLM, AutoProcessor  # type: ignore

            model_id = settings.dots_ocr_model
            eng = {
                "model": AutoModelForCausalLM.from_pretrained(
                    model_id, trust_remote_code=True, device_map="auto"
                ),
                "processor": AutoProcessor.from_pretrained(
                    model_id, trust_remote_code=True
                ),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("dots.ocr non inizializzabile: %s", exc)
            eng = None
        _ENGINES["dots_ocr"] = eng
    if eng is None:
        return ""
    try:
        from PIL import Image

        with Image.open(img_path) as im:
            image = im.convert("RGB")
        proc = eng["processor"]
        model = eng["model"]
        prompt = "Extract the text from the image."
        inputs = proc(text=prompt, images=image, return_tensors="pt").to(model.device)
        out = model.generate(**inputs, max_new_tokens=1024)
        text = proc.batch_decode(out, skip_special_tokens=True)
        return (text[0] if text else "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("dots.ocr fallito su %s: %s", img_path.name, exc)
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
    "paddleocr": lambda p, lang: _paddleocr(p, lang),
    "surya": lambda p, lang: _surya(p, lang),
    "dots_ocr": lambda p, lang: _dots_ocr(p),
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
