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
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.services.text_cleaning import strip_recurring_lines

logger = get_logger("extractor")

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


def _score_figure(width: int, height: int, caption: str) -> tuple[float, bool]:
    """Heuristic: is this embedded image worth including in the document?

    Combines the rendered size (decorative icons are small) with the amount of
    text recovered via OCR (charts/diagrams/schemas carry labels, photos and
    background art usually do not). Returns ``(score, suggested)``.
    """
    min_side = min(width, height)
    words = len(caption.split())
    score = 0.0
    if min_side >= 220:
        score += 0.5
    elif min_side >= 120:
        score += 0.3
    # A clearly non-square aspect ratio is typical of charts/diagrams.
    if max(width, height) >= 1.6 * max(min_side, 1):
        score += 0.1
    if words >= 4:
        score += 0.45
    elif words >= 1:
        score += 0.2
    score = round(min(score, 1.0), 3)
    return score, score >= 0.5


def _clean_caption(text: str) -> str:
    """Collapse OCR output into a short, single-line caption suggestion."""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat[:160]


# --------------------------------------------------------------------------- #
# OCR                                                                           #
# --------------------------------------------------------------------------- #
def tesseract_available() -> bool:
    """Return (and cache) whether the tesseract OCR engine is usable."""
    global _TESSERACT_OK
    if _TESSERACT_OK is not None:
        return _TESSERACT_OK
    try:
        import pytesseract  # type: ignore

        version = pytesseract.get_tesseract_version()
        logger.info(
            "OCR disponibile: tesseract %s (lingua=%s)", version, settings.ocr_lang
        )
        _TESSERACT_OK = True
    except Exception as exc:  # noqa: BLE001 - any failure means OCR is unusable
        logger.warning("OCR richiesto ma tesseract non utilizzabile: %s", exc)
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
    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        raise NotImplementedError

    def extract_figures(self, pdf_path: Path, figures_dir: Path) -> list[FigureInfo]:
        """Extract only the embedded figures (fast path used at upload time)."""
        return []


class PyMuPDFExtractor(BaseExtractor):
    """Default extractor: per-page text + embedded figures, with optional OCR fallback."""

    def __init__(self, render_dpi: int = 130, enable_ocr: bool = False) -> None:
        self.render_dpi = render_dpi
        self.enable_ocr = enable_ocr

    def extract_figures(self, pdf_path: Path, figures_dir: Path) -> list[FigureInfo]:
        import fitz  # PyMuPDF

        figures_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        slug = _slug(pdf_path.name)
        seen_xrefs: set[int] = set()
        out: list[FigureInfo] = []
        for i, page in enumerate(doc, start=1):
            if len(out) >= MAX_FIGURES_PER_DOC:
                break
            out.extend(
                self._extract_page_figures(
                    fitz, doc, page, figures_dir, slug, i, seen_xrefs, ocr_figures=True
                )
            )
        doc.close()
        logger.info("Estratte %d figure da %s", len(out), pdf_path.name)
        return out

    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
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

        ocr_active = self.enable_ocr and tesseract_available()
        for i, page in enumerate(doc, start=1):
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
                ocr_text = _ocr_image(img_path)
                if ocr_text:
                    text = ocr_text
                    source = "ocr"
                    ocr_used += 1

            # Extract embedded raster figures on this page.
            if len(figures) < MAX_FIGURES_PER_DOC:
                figures.extend(
                    fi.rel_path
                    for fi in self._extract_page_figures(
                        fitz, doc, page, figures_dir, slug, i, seen_xrefs
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
    ) -> list[FigureInfo]:
        out: list[FigureInfo] = []
        for idx, info in enumerate(page.get_images(full=True), start=1):
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
                caption = ""
                if ocr_figures:
                    caption = _clean_caption(_ocr_image(fig_path))
                score, suggested = _score_figure(pix.width, pix.height, caption)
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


def docling_markdown_chunked(pdf_path: Path) -> str | None:
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
            md = _run_docling_chunk(slice_pdf, settings.docling_subprocess_timeout)
            if md:
                parts.append(md)
                ok_chunks += 1

    if not parts:
        logger.warning("Docling: nessun chunk riuscito per %s", pdf_path.name)
        return None

    merged = "\n\n".join(parts).strip()
    logger.info(
        "Docling: %s completato (%d/%d chunk, %d caratteri)",
        pdf_path.name,
        ok_chunks,
        n_chunks,
        len(merged),
    )
    if settings.extraction_cache and merged:
        try:
            cache_path.write_text(merged, encoding="utf-8")
        except OSError:
            pass
    return merged or None


class DoclingExtractor(BaseExtractor):
    """Structured extraction via Docling (rich markdown, no embedded figures)."""

    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        markdown = docling_markdown_chunked(pdf_path) or ""
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

    def __init__(self, render_dpi: int = 130, enable_ocr: bool = True) -> None:
        self._py = PyMuPDFExtractor(render_dpi=render_dpi, enable_ocr=enable_ocr)

    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        doc = self._py.extract(pdf_path, figures_dir)

        # Remove running headers/footers from the per-page text (improves both
        # the PyMuPDF fallback and any downstream analysis).
        if settings.dedup_headers_footers and doc.pages:
            cleaned = strip_recurring_lines([p.text for p in doc.pages])
            for page, text in zip(doc.pages, cleaned):
                page.text = text

        rich = docling_markdown_chunked(pdf_path)
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


def get_extractor(
    backend: str | None = None,
    enable_ocr: bool | None = None,
) -> BaseExtractor:
    """Return an extractor instance for the configured (or requested) backend."""
    backend = (backend or settings.extractor_backend).lower()
    ocr = settings.enable_ocr if enable_ocr is None else enable_ocr
    if ocr and not tesseract_available():
        logger.warning("OCR richiesto ma non disponibile: proseguo senza OCR.")
    logger.info("Extractor backend=%s ocr=%s", backend, ocr)
    if backend == "docling":
        return DoclingExtractor()
    if backend == "pymupdf":
        return PyMuPDFExtractor(render_dpi=settings.render_dpi, enable_ocr=ocr)
    # Default: hybrid (Docling text + PyMuPDF figures + OCR fallback).
    return HybridExtractor(render_dpi=settings.render_dpi, enable_ocr=ocr)


def extract_figures(pdf_path: Path, figures_dir: Path) -> list[FigureInfo]:
    """Extract embedded figures from a PDF (PyMuPDF) with OCR-based scoring."""
    return PyMuPDFExtractor(render_dpi=settings.render_dpi).extract_figures(
        pdf_path, figures_dir
    )


def available_backends() -> dict[str, bool]:
    """Report which extractor backends/capabilities are available."""
    import importlib.util

    has_docling = importlib.util.find_spec("docling") is not None
    return {
        # Hybrid always works (it degrades to PyMuPDF when Docling is absent).
        "hybrid": True,
        "pymupdf": importlib.util.find_spec("fitz") is not None,
        "docling": has_docling,
        "ocr": importlib.util.find_spec("pytesseract") is not None,
    }
