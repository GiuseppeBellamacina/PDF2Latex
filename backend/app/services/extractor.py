"""Pluggable PDF extraction.

A backend turns a PDF into a list of :class:`PageContent` (text + an optional
rendered image path). The recommended backend is ``hybrid``: it uses Docling
for rich, structured text (including tables) and PyMuPDF for the embedded
figures, with an OCR fallback for image-only pages. ``pymupdf`` (fast) and
``docling`` (text only) remain available as explicit choices.

Memory safety: Docling loads heavy ML models and can blow up on large PDFs
(``std::bad_alloc``). It is therefore **never run in-process** here. Instead the
PDF is sliced into small page-range chunks, each converted in an isolated
subprocess (:mod:`app.services.docling_worker`) one at a time, and the markdown
is merged. The OS reclaims memory between chunks. Results are cached by file
hash so retries and re-runs are fast.

The figure extraction step also runs OCR on each embedded image so that we can
(a) read data out of charts/diagrams and (b) recommend which figures are worth
including in the final document.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.services import pipeline
from app.services.ocr_engines import engine_available as ocr_engine_available
from app.services.ocr_engines import run_ocr
from app.services.text_cleaning import strip_recurring_lines

logger = get_logger("extractor")


def _ocr_engine_ready(engine: str) -> bool:
    """Whether the selected OCR engine can actually run.

    Tesseract additionally needs its system binary; the other engines only need
    their Python package to be importable.
    """
    if engine == "tesseract":
        return tesseract_available()
    return ocr_engine_available(engine)


# A progress callback receives a UI-ready event dict (stage/message/detail/...).
ProgressCb = Callable[[dict], None] | None


def _notify(progress: ProgressCb, **event) -> None:
    """Best-effort progress emit (never let UI plumbing break extraction)."""
    if progress is None:
        return
    try:
        event.setdefault("stage", "extracting")
        progress(event)
    except Exception as exc:  # noqa: BLE001 - progress is best-effort
        logger.debug("progress callback fallita: %s", exc)


# Embedded images smaller than this (in pixels, on either side) are treated as
# decorative icons/logos and skipped.
MIN_FIGURE_SIDE = 80
# Hard cap on figures per document to avoid pathological slide decks.
MAX_FIGURES_PER_DOC = 40
# Below this many characters a page is considered "image-only" and (if OCR is
# enabled) gets a rendered-image OCR pass.
OCR_TEXT_THRESHOLD = 16

# Cached availability of the tesseract binary (None = not yet checked).
_TESSERACT_OK: bool | None = None


def _slug(name: str) -> str:
    stem = Path(name).stem.lower()
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "doc"


def _file_hash(pdf_path: Path) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:32]


def _caption_quality(text: str) -> float:
    """Rate how convincing a caption looks (0.0–1.0).

    A real caption is a short descriptive sentence, not OCR noise. We reward
    longer text (up to ~15 words) with a reasonable average word length, and
    penalise strings dominated by short gibberish tokens (common OCR artefact).
    """
    words = [w for w in text.split() if len(w) >= 2]
    n = len(words)
    if n < 2:
        return 0.0
    avg_len = sum(len(w) for w in words) / n
    # Reward word count up to 15; reward average word length 3–9.
    count_score = min(n / 15.0, 1.0)
    len_score = max(0.0, min((avg_len - 2.5) / 6.0, 1.0))
    # Penalise strings dominated by very short tokens (common OCR artefact).
    gibberish_penalty = sum(1 for w in words if len(w) <= 2) / max(n, 1)
    score = count_score * 0.5 + len_score * 0.5 - gibberish_penalty * 0.4
    return round(max(0.0, min(score, 1.0)), 3)


def _score_figure(
    width: int,
    height: int,
    caption: str,
    has_real_caption: bool = False,
    caption_confidence: float = 0.0,
    page_context: dict | None = None,
) -> tuple[float, bool]:
    """Heuristic: is this embedded image worth including in the document?

    Combines rendered size, aspect ratio, position on page, caption quality,
    and page-level context (density, competition). Charts/diagrams/schemas tend
    to be medium/large with a diagram-like aspect ratio and carry labels;
    decorative icons are tiny, banners/rules are extremely elongated, and
    full-slide screenshots are huge.

    Args:
        width, height: Rendered image dimensions in pixels.
        caption: OCR or PDF caption text (may be empty).
        has_real_caption: True when a PDF-laid-out caption was found.
        caption_confidence: 0.0–1.0 confidence of the caption assignment.
        page_context: Optional dict with keys ``y0``, ``page_height``,
            ``n_figures_on_page``, ``page_text_len``.

    Returns ``(score, suggested)``.
    """
    min_side = min(width, height)
    max_side = max(width, height)
    aspect = max_side / max(min_side, 1)

    score = 0.0
    # ── Size (primary signal) ─────────────────────────────────────────────
    if min_side < 110:
        score += 0.0  # decorative icon/logo
    elif min_side < 200:
        score += 0.35
    elif min_side < 1000:
        score += 0.6  # solid content figure
    else:
        score += 0.5  # very large (often a full-slide screenshot)

    # ── Aspect ratio ──────────────────────────────────────────────────────
    if 1.15 <= aspect <= 2.8:
        score += 0.10
    elif aspect > 4.0:
        score -= 0.3

    # ── Caption quality ───────────────────────────────────────────────────
    cap_qual = _caption_quality(caption)
    if cap_qual >= 0.6:
        score += 0.25
    elif cap_qual >= 0.3:
        score += 0.15
    elif cap_qual >= 0.1:
        score += 0.06

    # PDF-laid-out caption is strong evidence → bonus + confidence boost.
    if has_real_caption:
        score += 0.15 + caption_confidence * 0.10

    # ── Page-level context (density, position, competition) ────────────────
    if page_context:
        n_figures = page_context.get("n_figures_on_page", 0)
        y0 = page_context.get("y0", 0.0)
        ph = page_context.get("page_height", 800.0)
        text_len = page_context.get("page_text_len", 0)

        # Position bonus: figures in the top third of a page are often key.
        if ph > 0 and y0 / ph < 0.30:
            score += 0.08

        # Competition penalty: many figures on one page (slide deck, gallery).
        if n_figures > 3:
            score -= 0.06 * (n_figures - 3)
        elif n_figures == 1:
            score += 0.05  # sole figure on page → likely important

        # Density penalty: heavy-text pages with inline figures are often minor.
        if text_len > 4000 and min_side < 600:
            score -= 0.08

    score = round(max(0.0, min(score, 1.0)), 3)
    # Threshold: lower when we have strong caption evidence.
    threshold = 0.45 if (has_real_caption and caption_confidence >= 0.6) else 0.52
    return score, score >= threshold


def _clean_caption(text: str) -> str:
    """Collapse OCR output into a short, single-line caption suggestion."""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat[:160]


# Leading "Figura 3:", "Fig. 2 -", "Tabella 1.", "Schema 4)", etc. in many
# languages. Used both to recognise a caption block and to strip its label so
# LaTeX's own "Figura N:" prefix isn't duplicated.
_CAPTION_LABEL_RE = re.compile(
    r"^\s*(?:fig(?:ura|ure|\.)?|tab(?:ella|le|\.)?|grafico|graph|chart|"
    r"schema|scheme|immagine|image|diagramma|diagram|plot|"
    r"esempio|example|(?:supplementary\s+)?figure|(?:illustrazione|illustration))"
    r"\s*\.?\s*\d{0,3}[a-z]?\s*[\.:)\u2013\u2014\-]?\s*",
    re.IGNORECASE,
)

# Capture the figure/table number from a caption label for matching.
_CAPTION_NUMBER_RE = re.compile(r"(\d+)", re.IGNORECASE)


def _find_pdf_caption(  # type: ignore[no-untyped-def]
    page, rect, max_gap: float = 90.0, return_confidence: bool = False
) -> str | tuple[str, float]:
    """Find the real caption text laid out near a figure in the source PDF.

    Multi-zone search: checks BELOW (preferred), RIGHT, ABOVE, and LEFT of the
    figure bounding box, in that priority order. A block starting with a
    caption keyword (``Figura 3:`` …) wins over unlabelled neighbours. When no
    immediate neighbour is plausible, a wider-context fallback scans the entire
    page for figure-number mentions near the image's vertical position — such
    captions are returned with a low confidence score.

    Args:
        page: PyMuPDF page object.
        rect: PyMuPDF Rect for the image.
        max_gap: Maximum pixel gap between figure edge and caption block.
        return_confidence: If True, return ``(caption, confidence)``.

    Returns:
        The cleaned caption string, or ``""``. When ``return_confidence=True``
        a ``(str, float)`` tuple is returned (0.0–1.0 confidence).
    """
    try:
        blocks = page.get_text("blocks")
    except Exception:  # noqa: BLE001 - layout text is best-effort
        return ("", 0.0) if return_confidence else ""

    ix0, iy0, ix1, iy1 = rect.x0, rect.y0, rect.x1, rect.y1
    iw = max(ix1 - ix0, 1.0)
    ih = max(iy1 - iy0, 1.0)
    best: tuple[int, float, str, bool] | None = None  # (priority, gap, text, kw)

    for b in blocks:
        if len(b) < 5:
            continue
        bx0, by0, bx1, by1, raw = b[0], b[1], b[2], b[3], b[4]
        text = re.sub(r"\s+", " ", str(raw)).strip()
        if len(text) < 3 or len(text) > 500:
            continue

        # Measure overlap in both axes to support multi-zone (below/above/left/right).
        overlap_x = max(0.0, min(ix1, bx1) - max(ix0, bx0))
        overlap_y = max(0.0, min(iy1, by1) - max(iy0, by0))

        below_gap = by0 - iy1
        above_gap = iy0 - by1
        right_gap = bx0 - ix1
        left_gap = ix0 - bx1

        # Determine zone and gap.
        zone: str | None = None
        gap: float = 9999.0

        # Below: meaningful horizontal overlap, small vertical gap.
        if overlap_x / iw >= 0.30 and 0 <= below_gap <= max_gap:
            zone, gap = "below", below_gap
        # Right: meaningful vertical overlap, small horizontal gap.
        elif overlap_y / ih >= 0.30 and 0 <= right_gap <= max_gap * 1.5:
            zone, gap = "right", right_gap
        # Above: meaningful horizontal overlap, small vertical gap.
        elif overlap_x / iw >= 0.30 and 0 <= above_gap <= max_gap:
            zone, gap = "above", above_gap
        # Left: meaningful vertical overlap, small horizontal gap.
        elif overlap_y / ih >= 0.30 and 0 <= left_gap <= max_gap * 1.5:
            zone, gap = "left", left_gap

        if zone is None:
            continue

        has_kw = bool(_CAPTION_LABEL_RE.match(text))
        # Priority: below-kw (0) < right-kw/above-kw (1) < below-plain (2)
        #          < right-plain/above-plain (3) < left (4)
        zone_order = {"below": 0, "right": 1, "above": 1, "left": 2}
        priority = (zone_order[zone] * 2) + (0 if has_kw else 1)
        cand = (priority, gap, text, has_kw)
        if best is None or (cand[0], cand[1]) < (best[0], best[1]):
            best = cand

    # ── Wider-context fallback ───────────────────────────────────────────
    confidence = 0.0
    if best is None:
        # Scan the full page for figure-number mentions near the image's Y.
        img_mid_y = (iy0 + iy1) / 2.0
        page_texts: list[tuple[float, str, bool]] = []  # (y-distance, text, kw)
        for b in blocks:
            if len(b) < 5:
                continue
            _, by0, _, _, raw = b
            text = re.sub(r"\s+", " ", str(raw)).strip()
            if len(text) < 4 or len(text) > 500:
                continue
            kw = bool(_CAPTION_LABEL_RE.match(text))
            b_mid_y = by0
            dist = abs(b_mid_y - img_mid_y)
            page_texts.append((dist, text, kw))
        if page_texts:
            page_texts.sort(key=lambda x: (0 if x[2] else 1, x[0]))
            closest_dist, closest_text, closest_kw = page_texts[0]
            if closest_kw or closest_dist < max_gap * 4:
                best = (10, closest_dist, closest_text, closest_kw)
                confidence = 0.35 if closest_kw else 0.20

    if best is None:
        return ("", 0.0) if return_confidence else ""

    _, _gap, text, keyword = best
    if best[0] >= 10:
        pass  # confidence already set by fallback
    elif keyword:
        zone_letter = {0: 1.0, 1: 0.9, 2: 0.70}
        confidence = zone_letter.get(best[0] // 2, 0.80)
    else:
        confidence = 0.55

    if keyword:
        text = _CAPTION_LABEL_RE.sub("", text, count=1).strip()
    caption = _clean_caption(text)
    return (caption, round(confidence, 2)) if return_confidence else caption


# --------------------------------------------------------------------------- #
# OCR                                                                           #
# --------------------------------------------------------------------------- #
def _resolve_tesseract_cmd() -> str | None:
    """Find the tesseract executable: explicit setting -> PATH -> common dirs.

    On Windows the winget/UB-Mannheim installer adds tesseract to PATH, but a
    process started before the install (or a service) won't see the updated
    PATH. So we also probe the standard install locations and, when found, point
    pytesseract straight at the binary.
    """
    import shutil

    candidates: list[str] = []
    if settings.tesseract_cmd:
        candidates.append(settings.tesseract_cmd)
    on_path = shutil.which("tesseract")
    if on_path:
        candidates.append(on_path)
    candidates += [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        str(Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe"),
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            return cand
    return on_path  # may be None


def tesseract_available() -> bool:
    """Return (and cache) whether the tesseract OCR engine is usable."""
    global _TESSERACT_OK
    if _TESSERACT_OK is not None:
        return _TESSERACT_OK
    try:
        import pytesseract  # type: ignore

        # Point pytesseract at the resolved binary if it isn't already on PATH.
        cmd = _resolve_tesseract_cmd()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

        version = pytesseract.get_tesseract_version()
        logger.info(
            "OCR disponibile: tesseract %s (%s, lingua=%s)",
            version,
            cmd or "su PATH",
            settings.ocr_lang,
        )
        _TESSERACT_OK = True
    except Exception as exc:  # noqa: BLE001 - any failure means OCR is unusable
        logger.warning(
            "OCR non disponibile: %s. Installa il binario Tesseract "
            "(Windows: 'winget install UB-Mannheim.TesseractOCR' oppure "
            "https://github.com/UB-Mannheim/tesseract/wiki) e assicurati che "
            "'tesseract' sia nel PATH (oppure imposta PDF2TEX_TESSERACT_CMD col "
            "percorso a tesseract.exe); per le lingue installa i language pack "
            "(es. ita, eng). Variabile: PDF2TEX_OCR_LANG=%s",
            exc,
            settings.ocr_lang,
        )
        _TESSERACT_OK = False
    return _TESSERACT_OK


def _ocr_image(img_path: Path) -> str:
    """Run OCR on an image, honouring the configured language. Best-effort."""
    if not tesseract_available():
        return ""
    try:
        import pytesseract  # type: ignore
        from PIL import Image

        with Image.open(img_path) as im:
            text = pytesseract.image_to_string(im, lang=settings.ocr_lang)
        return text.strip()
    except Exception as exc:  # noqa: BLE001 - OCR is best-effort
        logger.debug("OCR fallito su %s: %s", img_path.name, exc)
        return ""


@dataclass
class PageContent:
    page: int
    text: str
    image_path: str | None = None  # full-page render (used for OCR fallback)
    source: str = "pymupdf"


@dataclass
class ExtractedDocument:
    filename: str
    pages: list[PageContent] = field(default_factory=list)
    # Relative paths (e.g. "figures/foo_p1_1.png") of embedded figures.
    figures: list[str] = field(default_factory=list)
    # Optional rich markdown (e.g. from Docling) used as the primary text when set.
    rich_markdown: str | None = None

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    def full_text(self) -> str:
        if self.rich_markdown:
            return self.rich_markdown
        return "\n\n".join(
            f"===== PAGINA {p.page}/{self.n_pages} =====\n{p.text}" for p in self.pages
        )


@dataclass
class FigureInfo:
    rel_path: str
    page: int
    caption: str = ""
    score: float = 0.0
    suggested: bool = False


class BaseExtractor:
    def extract(
        self, pdf_path: Path, figures_dir: Path, progress: ProgressCb = None
    ) -> ExtractedDocument:
        raise NotImplementedError

    def extract_figures(self, pdf_path: Path, figures_dir: Path) -> list[FigureInfo]:
        """Extract only the embedded figures (fast path used at upload time)."""
        return []


class PyMuPDFExtractor(BaseExtractor):
    """Default extractor: per-page text + embedded figures, with optional OCR fallback."""

    def __init__(
        self,
        render_dpi: int = 130,
        enable_ocr: bool = False,
        ocr_engine: str = "tesseract",
        ocr_lang: str | None = None,
    ) -> None:
        self.render_dpi = render_dpi
        self.enable_ocr = enable_ocr
        self.ocr_engine = ocr_engine
        self.ocr_lang = ocr_lang or settings.ocr_lang

    def extract_figures(self, pdf_path: Path, figures_dir: Path) -> list[FigureInfo]:
        import fitz  # PyMuPDF

        figures_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        slug = _slug(pdf_path.name)
        seen_xrefs: set[int] = set()
        out: list[FigureInfo] = []
        for i in range(1, doc.page_count + 1):
            if len(out) >= MAX_FIGURES_PER_DOC:
                break
            page = doc.load_page(i - 1)
            out.extend(
                self._extract_page_figures(
                    fitz,
                    doc,
                    page,
                    figures_dir,
                    slug,
                    i,
                    seen_xrefs,
                    ocr_figures=True,
                    ocr_engine=self.ocr_engine,
                    ocr_lang=self.ocr_lang,
                )
            )
        doc.close()
        logger.info("Estratte %d figure da %s", len(out), pdf_path.name)
        return out

    def extract(
        self, pdf_path: Path, figures_dir: Path, progress: ProgressCb = None
    ) -> ExtractedDocument:
        import fitz  # PyMuPDF

        figures_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        zoom = self.render_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        slug = _slug(pdf_path.name)

        pages: list[PageContent] = []
        figures: list[str] = []
        seen_xrefs: set[int] = set()
        ocr_used = 0

        ocr_active = self.enable_ocr and _ocr_engine_ready(self.ocr_engine)
        _notify(
            progress,
            message=f"PyMuPDF: lettura di {pdf_path.name}",
            detail=(
                f"OCR {'attivo (' + self.ocr_engine + ')' if ocr_active else 'non attivo'}"
            ),
        )
        for i in range(1, doc.page_count + 1):
            page = doc.load_page(i - 1)
            text = page.get_text("text").strip()

            source = "pymupdf"
            img_path_str: str | None = None
            # Lazily render the full page ONLY when OCR is needed (text-poor
            # page) — avoids one PNG per page on text PDFs.
            if ocr_active and len(text) < OCR_TEXT_THRESHOLD:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_path = figures_dir / f"render_{slug}_p{i:03d}.png"
                pix.save(img_path)
                img_path_str = str(img_path)
                ocr_text = run_ocr(img_path, self.ocr_lang, self.ocr_engine)
                if ocr_text:
                    text = ocr_text
                    source = "ocr"
                    ocr_used += 1

            # Extract embedded raster figures on this page.
            if len(figures) < MAX_FIGURES_PER_DOC:
                figures.extend(
                    fi.rel_path
                    for fi in self._extract_page_figures(
                        fitz,
                        doc,
                        page,
                        figures_dir,
                        slug,
                        i,
                        seen_xrefs,
                        ocr_engine=self.ocr_engine,
                        ocr_lang=self.ocr_lang,
                    )
                )

            pages.append(
                PageContent(page=i, text=text, image_path=img_path_str, source=source)
            )

        doc.close()
        logger.info(
            "PyMuPDF: %s -> %d pagine, %d figure, %d pagine via OCR",
            pdf_path.name,
            len(pages),
            len(figures),
            ocr_used,
        )
        _notify(
            progress,
            message=f"PyMuPDF: {pdf_path.name} letto",
            detail=f"{len(pages)} pagine, {len(figures)} figure, {ocr_used} via OCR",
            level="success",
        )
        return ExtractedDocument(filename=pdf_path.name, pages=pages, figures=figures)

    @staticmethod
    def _extract_page_figures(
        fitz,  # noqa: ANN001 - module handle
        doc,  # noqa: ANN001
        page,  # noqa: ANN001
        figures_dir: Path,
        slug: str,
        page_no: int,
        seen_xrefs: set[int],
        ocr_figures: bool = False,
        ocr_engine: str = "tesseract",
        ocr_lang: str | None = None,
    ) -> list[FigureInfo]:
        out: list[FigureInfo] = []
        all_images = page.get_images(full=True)
        n_total = len(all_images)
        page_text_len = len(page.get_text("text").strip())
        page_rect = page.rect
        page_height = page_rect.y1 - page_rect.y0

        for idx, info in enumerate(all_images, start=1):
            xref = info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                pix = fitz.Pixmap(doc, xref)
                if min(pix.width, pix.height) < MIN_FIGURE_SIDE:
                    continue
                # Normalize colorspace to RGB for a PNG we can embed in LaTeX.
                if pix.n >= 5 or pix.alpha:  # CMYK / with alpha
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                fig_path = figures_dir / f"fig_{slug}_p{page_no:03d}_{idx}.png"
                pix.save(fig_path)
                # Prefer the REAL caption laid out next to the figure in the
                # PDF; this binds a correct caption to the image and avoids the
                # swapped/wrong captions produced by OCR-ing the pixels.
                rect = None
                try:
                    rects = page.get_image_rects(xref)
                    if rects:
                        rect = rects[0]
                except Exception:  # noqa: BLE001 - rect lookup is best-effort
                    rect = None
                pdf_caption, caption_conf = (
                    _find_pdf_caption(page, rect, return_confidence=True)
                    if rect is not None
                    else ("", 0.0)
                )
                ocr_text = (
                    run_ocr(fig_path, ocr_lang or settings.ocr_lang, ocr_engine)
                    if ocr_figures
                    else ""
                )
                caption = pdf_caption or _clean_caption(ocr_text)
                # Build per-figure page context for density-aware scoring.
                ctx = {
                    "y0": rect.y0 if rect else 0.0,
                    "page_height": page_height,
                    "n_figures_on_page": n_total,
                    "page_text_len": page_text_len,
                }
                score, suggested = _score_figure(
                    pix.width,
                    pix.height,
                    ocr_text or pdf_caption,
                    has_real_caption=bool(pdf_caption),
                    caption_confidence=caption_conf,
                    page_context=ctx,
                )
                out.append(
                    FigureInfo(
                        rel_path=f"figures/{fig_path.name}",
                        page=page_no,
                        caption=caption,
                        score=score,
                        suggested=suggested,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - skip un-extractable images
                logger.debug("Figura non estraibile (xref=%s): %s", xref, exc)
                continue
        return out


# --------------------------------------------------------------------------- #
# Docling (isolated subprocess, chunked, cached)                                #
# --------------------------------------------------------------------------- #
def _docling_cache_path(pdf_path: Path) -> Path:
    key = f"{_file_hash(pdf_path)}-t{int(settings.docling_enable_tables)}"
    cache_dir = settings.cache_dir / "docling"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{key}.md"


def _run_docling_chunk(slice_pdf: Path, timeout: int) -> str | None:
    """Convert one (small) PDF slice via the isolated worker subprocess."""
    out_md = slice_pdf.with_suffix(".md")
    cmd = [
        sys.executable,
        "-m",
        "app.services.docling_worker",
        str(slice_pdf),
        str(out_md),
    ]
    if settings.docling_enable_tables:
        cmd.append("--tables")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("Docling: timeout (%ss) sul chunk %s", timeout, slice_pdf.name)
        return None
    if proc.returncode != 0:
        logger.warning(
            "Docling chunk %s fallito (rc=%s): %s",
            slice_pdf.name,
            proc.returncode,
            (proc.stderr or "").strip()[-300:],
        )
        return None
    try:
        return out_md.read_text(encoding="utf-8")
    except OSError:
        return None


def docling_markdown_chunked(pdf_path: Path, progress: ProgressCb = None) -> str | None:
    """Convert a PDF to structured markdown via Docling, safely.

    Steps: cache lookup -> page-count guard -> slice into chunks -> isolated
    subprocess per chunk (sequential) -> merge -> cache. Returns ``None`` if
    Docling is unavailable, the PDF is too large, or every chunk fails (the
    caller then falls back to PyMuPDF text).
    """
    import importlib.util

    if importlib.util.find_spec("docling") is None:
        return None

    cache_path = _docling_cache_path(pdf_path)
    if settings.extraction_cache and cache_path.exists():
        logger.info("Docling: cache hit per %s", pdf_path.name)
        _notify(
            progress,
            message=f"Docling: {pdf_path.name} da cache",
            detail="testo strutturato riusato dalla cache",
        )
        return cache_path.read_text(encoding="utf-8") or None

    import fitz  # PyMuPDF

    with fitz.open(pdf_path) as doc:
        n_pages = doc.page_count
    if settings.docling_max_pages and n_pages > settings.docling_max_pages:
        logger.info(
            "Docling: %s ha %d pagine (> %d), uso solo PyMuPDF",
            pdf_path.name,
            n_pages,
            settings.docling_max_pages,
        )
        _notify(
            progress,
            message=f"Docling saltato per {pdf_path.name}",
            detail=f"{n_pages} pagine oltre il limite di {settings.docling_max_pages}",
            level="warning",
        )
        return None

    chunk_size = max(1, settings.docling_chunk_pages)
    n_chunks = (n_pages + chunk_size - 1) // chunk_size
    logger.info(
        "Docling: %s -> %d pagine in %d chunk(s) da %d (sottoprocessi isolati)",
        pdf_path.name,
        n_pages,
        n_chunks,
        chunk_size,
    )
    _notify(
        progress,
        message=f"Docling: {pdf_path.name} in {n_chunks} blocchi",
        detail=f"{n_pages} pagine, {chunk_size} pagine per blocco (sottoprocessi isolati)",
    )

    parts: list[str] = []
    ok_chunks = 0
    with tempfile.TemporaryDirectory(prefix="docling_") as tmp:
        tmp_dir = Path(tmp)
        for ci in range(n_chunks):
            start = ci * chunk_size
            end = min(start + chunk_size, n_pages)
            slice_pdf = tmp_dir / f"chunk_{ci:03d}.pdf"
            # Build a small PDF holding just this page range.
            src = fitz.open(pdf_path)
            dst = fitz.open()
            dst.insert_pdf(src, from_page=start, to_page=end - 1)
            dst.save(slice_pdf)
            dst.close()
            src.close()

            logger.info(
                "Docling: chunk %d/%d (pagine %d-%d)", ci + 1, n_chunks, start + 1, end
            )
            _notify(
                progress,
                message=f"Docling: blocco {ci + 1}/{n_chunks} di {pdf_path.name}",
                detail=f"pagine {start + 1}-{end}",
            )
            md = _run_docling_chunk(slice_pdf, settings.docling_subprocess_timeout)
            if md:
                parts.append(md)
                ok_chunks += 1
            else:
                _notify(
                    progress,
                    message=f"Docling: blocco {ci + 1}/{n_chunks} non riuscito",
                    detail=f"{pdf_path.name} pagine {start + 1}-{end}",
                    level="warning",
                )

    if not parts:
        logger.warning("Docling: nessun chunk riuscito per %s", pdf_path.name)
        _notify(
            progress,
            message=f"Docling fallito per {pdf_path.name}",
            detail="uso il testo PyMuPDF",
            level="warning",
        )
        return None

    merged = "\n\n".join(parts).strip()
    logger.info(
        "Docling: %s completato (%d/%d chunk, %d caratteri)",
        pdf_path.name,
        ok_chunks,
        n_chunks,
        len(merged),
    )
    _notify(
        progress,
        message=f"Docling: {pdf_path.name} completato",
        detail=f"{ok_chunks}/{n_chunks} blocchi, {len(merged)} caratteri",
        level="success",
    )
    if settings.extraction_cache and merged:
        try:
            cache_path.write_text(merged, encoding="utf-8")
        except OSError:
            pass
    return merged or None


class DoclingExtractor(BaseExtractor):
    """Structured extraction via Docling (rich markdown, no embedded figures)."""

    def extract(
        self, pdf_path: Path, figures_dir: Path, progress: ProgressCb = None
    ) -> ExtractedDocument:
        markdown = docling_markdown_chunked(pdf_path, progress) or ""
        pages = [PageContent(page=1, text=markdown, source="docling")]
        return ExtractedDocument(
            filename=pdf_path.name, pages=pages, rich_markdown=markdown or None
        )


class HybridExtractor(BaseExtractor):
    """Recommended backend: Docling text (chunked) + PyMuPDF figures + OCR fallback.

    PyMuPDF provides per-page text (with an OCR fallback for image-only pages)
    and the embedded figures; Docling, when available, supplies a richer,
    structured markdown (tables included) that becomes the primary text fed to
    the model. If Docling is missing or fails, the result gracefully degrades to
    plain PyMuPDF output.
    """

    def __init__(
        self,
        render_dpi: int = 130,
        enable_ocr: bool = True,
        ocr_engine: str = "tesseract",
        ocr_lang: str | None = None,
    ) -> None:
        self._py = PyMuPDFExtractor(
            render_dpi=render_dpi,
            enable_ocr=enable_ocr,
            ocr_engine=ocr_engine,
            ocr_lang=ocr_lang,
        )

    def extract(
        self, pdf_path: Path, figures_dir: Path, progress: ProgressCb = None
    ) -> ExtractedDocument:
        doc = self._py.extract(pdf_path, figures_dir, progress)

        # Remove running headers/footers from the per-page text (improves both
        # the PyMuPDF fallback and any downstream analysis).
        if settings.dedup_headers_footers and doc.pages:
            cleaned = strip_recurring_lines([p.text for p in doc.pages])
            for page, text in zip(doc.pages, cleaned):
                page.text = text

        rich = docling_markdown_chunked(pdf_path, progress)
        if rich:
            doc.rich_markdown = rich
        else:
            logger.info(
                "Hybrid: uso testo PyMuPDF per %s (Docling non disponibile)",
                pdf_path.name,
            )
        return doc

    def extract_figures(self, pdf_path: Path, figures_dir: Path) -> list[FigureInfo]:
        return self._py.extract_figures(pdf_path, figures_dir)


class PipelineExtractor(BaseExtractor):
    """Composable extractor driven by a per-project pipeline config.

    Orchestrates the selected tool for each stage:

    * **text** — PyMuPDF per-page text (always);
    * **structure** — rich markdown (Docling / Marker / MinerU) used as primary
      text when available, else PyMuPDF text;
    * **ocr** — engine used for image-only pages and figure label reading;
    * **math** — Nougat math-rich markdown appended when enabled;
    * **figures** — PyMuPDF embedded-figure extraction;
    * **figure_scoring** — heuristic, optionally OCR-assisted (the ``vlm`` option
      is applied later, with the LLM, in the runner).

    Falls back gracefully when an optional engine is missing.
    """

    def __init__(
        self,
        config: dict | None = None,
        enable_ocr: bool = False,
        render_dpi: int | None = None,
        ocr_lang: str | None = None,
    ) -> None:
        self.config = pipeline.normalize_pipeline_config(config)
        self.enable_ocr = enable_ocr
        self.render_dpi = render_dpi or settings.render_dpi
        self.ocr_engine = self.config.get("ocr", "tesseract")
        # Figure scoring "ocr_assisted" reads labels inside figures via OCR.
        scoring = self.config.get("figure_scoring", "heuristic")
        score_with_ocr = scoring == "ocr_assisted" and self.enable_ocr
        self._py = PyMuPDFExtractor(
            render_dpi=self.render_dpi,
            enable_ocr=self.enable_ocr or score_with_ocr,
            ocr_engine=self.ocr_engine,
            ocr_lang=ocr_lang,
        )

    def extract(
        self, pdf_path: Path, figures_dir: Path, progress: ProgressCb = None
    ) -> ExtractedDocument:
        from app.services import math_engines, structure_engines

        doc = self._py.extract(pdf_path, figures_dir, progress)

        if settings.dedup_headers_footers and doc.pages:
            cleaned = strip_recurring_lines([p.text for p in doc.pages])
            for page, text in zip(doc.pages, cleaned):
                page.text = text

        # Structure stage -> rich markdown as the primary text when available.
        structure_tool = self.config.get("structure", "none")
        if structure_tool and structure_tool != "none":
            rich = structure_engines.extract_structure(
                pdf_path, structure_tool, progress
            )
            if rich:
                doc.rich_markdown = rich
            else:
                logger.info(
                    "Pipeline: struttura '%s' non disponibile per %s, uso PyMuPDF",
                    structure_tool,
                    pdf_path.name,
                )

        # Math stage -> append math-rich markdown (Nougat) to the primary text.
        math_tool = self.config.get("math", "none")
        if math_tool == "nougat":
            mmd = math_engines.math_markdown(pdf_path, "nougat")
            if mmd:
                base = doc.rich_markdown or doc.full_text()
                doc.rich_markdown = f"{base}\n\n{mmd}".strip()
                _notify(
                    progress,
                    message=f"Nougat: matematica recuperata per {pdf_path.name}",
                    detail=f"{len(mmd)} caratteri",
                    level="success",
                )

        return doc

    def extract_figures(self, pdf_path: Path, figures_dir: Path) -> list[FigureInfo]:
        return self._py.extract_figures(pdf_path, figures_dir)


def get_extractor(
    backend: str | None = None,
    enable_ocr: bool | None = None,
    pipeline_config: dict | None = None,
    ocr_lang: str | None = None,
) -> BaseExtractor:
    """Return an extractor instance for the requested backend or pipeline config.

    When ``pipeline_config`` is provided (the dashboard's composable pipeline) a
    :class:`PipelineExtractor` is built. Otherwise the legacy
    ``hybrid``/``pymupdf``/``docling`` backends are used, so existing projects
    keep working unchanged.

    When the pipeline config explicitly selects an OCR engine (not ``"none"``),
    OCR is auto-enabled regardless of the ``enable_ocr`` flag, so the user's
    pipeline choice is always honoured.

    ``ocr_lang`` is the per-project OCR language (e.g. ``"ita+eng"``). When left
    empty, the global ``settings.ocr_lang`` is used as fallback.
    """
    ocr = settings.enable_ocr if enable_ocr is None else enable_ocr
    lang = ocr_lang or settings.ocr_lang

    if pipeline_config:
        cfg = pipeline.normalize_pipeline_config(pipeline_config)
        ocr_engine = cfg.get("ocr", "tesseract")
        # Auto-enable OCR when the pipeline config explicitly selects an engine.
        if ocr_engine and ocr_engine != "none":
            ocr = True
        if ocr and ocr_engine != "none" and not _ocr_engine_ready(ocr_engine):
            logger.warning(
                "OCR '%s' richiesto ma non disponibile: proseguo senza OCR.",
                ocr_engine,
            )
        logger.info("Extractor pipeline=%s ocr=%s lang=%s", cfg, ocr, lang)
        return PipelineExtractor(
            config=cfg,
            enable_ocr=ocr,
            render_dpi=settings.render_dpi,
            ocr_lang=lang,
        )

    backend = (backend or settings.extractor_backend).lower()
    if ocr and not tesseract_available():
        logger.warning("OCR richiesto ma non disponibile: proseguo senza OCR.")
    logger.info("Extractor backend=%s ocr=%s lang=%s", backend, ocr, lang)
    if backend == "docling":
        return DoclingExtractor()
    if backend == "pymupdf":
        return PyMuPDFExtractor(
            render_dpi=settings.render_dpi, enable_ocr=ocr, ocr_lang=lang
        )
    # Default: hybrid (Docling text + PyMuPDF figures + OCR fallback).
    return HybridExtractor(
        render_dpi=settings.render_dpi, enable_ocr=ocr, ocr_lang=lang
    )


def extract_figures(pdf_path: Path, figures_dir: Path) -> list[FigureInfo]:
    """Extract embedded figures from a PDF (PyMuPDF) with OCR-based scoring."""
    return PyMuPDFExtractor(render_dpi=settings.render_dpi).extract_figures(
        pdf_path, figures_dir
    )


def pdf_page_count(pdf_path: Path) -> int:
    """Return the number of pages in a PDF (0 if it can't be read)."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            return doc.page_count
    except Exception as exc:  # noqa: BLE001 - best-effort, never block upload
        logger.debug("Conteggio pagine fallito per %s: %s", pdf_path, exc)
        return 0


def available_backends() -> dict[str, bool]:
    """Report which extractor backends/capabilities are available.

    ``ocr`` reflects whether the **tesseract binary** is actually callable, not
    merely whether the ``pytesseract`` wrapper is importable — otherwise the UI
    would offer OCR that then silently does nothing at extraction time.
    """
    import importlib.util

    has_docling = importlib.util.find_spec("docling") is not None
    has_pytesseract = importlib.util.find_spec("pytesseract") is not None
    return {
        # Hybrid always works (it degrades to PyMuPDF when Docling is absent).
        "hybrid": True,
        "pymupdf": importlib.util.find_spec("fitz") is not None,
        "docling": has_docling,
        # True only if the tesseract executable is on PATH and runnable.
        "ocr": has_pytesseract and tesseract_available(),
    }
