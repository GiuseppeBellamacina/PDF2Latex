"""Pluggable PDF extraction.

A backend turns a PDF into a list of :class:`PageContent` (text + an optional
rendered image path). The recommended backend is ``hybrid``: it uses Docling
for rich, structured text and PyMuPDF for the embedded figures, with an OCR
fallback for image-only pages. ``pymupdf`` (fast) and ``docling`` (text only)
remain available as explicit choices.

The figure extraction step also runs OCR on each embedded image so that we can
(a) read data out of charts/diagrams and (b) recommend which figures are worth
including in the final document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

# Embedded images smaller than this (in pixels, on either side) are treated as
# decorative icons/logos and skipped.
MIN_FIGURE_SIDE = 80
# Hard cap on figures per document to avoid pathological slide decks.
MAX_FIGURES_PER_DOC = 40


def _slug(name: str) -> str:
    stem = Path(name).stem.lower()
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "doc"


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

        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_path = figures_dir / f"render_{slug}_p{i:03d}.png"
            pix.save(img_path)

            source = "pymupdf"
            if self.enable_ocr and len(text) < 16:
                ocr_text = self._ocr(img_path)
                if ocr_text:
                    text = ocr_text
                    source = "ocr"

            # Extract embedded raster figures on this page.
            if len(figures) < MAX_FIGURES_PER_DOC:
                figures.extend(
                    fi.rel_path
                    for fi in self._extract_page_figures(
                        fitz, doc, page, figures_dir, slug, i, seen_xrefs
                    )
                )

            pages.append(
                PageContent(page=i, text=text, image_path=str(img_path), source=source)
            )

        doc.close()
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
                    caption = _clean_caption(PyMuPDFExtractor._ocr(fig_path))
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
            except Exception:  # noqa: BLE001 - skip un-extractable images
                continue
        return out

    @staticmethod
    def _ocr(img_path: Path) -> str:
        try:
            import pytesseract  # type: ignore
            from PIL import Image

            return pytesseract.image_to_string(Image.open(img_path)).strip()
        except Exception:  # noqa: BLE001 - OCR is best-effort/optional
            return ""


def _docling_converter():  # noqa: ANN202 - docling type only available at runtime
    """Build (and cache) a Docling converter with its heavy OCR disabled.

    We run our own OCR (PyMuPDF + pytesseract), so Docling's built-in OCR
    (RapidOCR/ONNX) is redundant and, on large PDFs, exhausts memory with
    ``std::bad_alloc``. Disabling it keeps Docling fast and stable while we
    still get its structured markdown. The converter loads ML models once, so
    it is cached for the process lifetime.
    """
    global _DOCLING_CONVERTER
    if _DOCLING_CONVERTER is not None:
        return _DOCLING_CONVERTER

    from docling.datamodel.base_models import InputFormat  # type: ignore
    from docling.datamodel.pipeline_options import (  # type: ignore
        PdfPipelineOptions,
    )
    from docling.document_converter import (  # type: ignore
        DocumentConverter,
        PdfFormatOption,
    )

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False  # we handle OCR ourselves
    # Keep memory low: don't generate/keep page or picture images (we use
    # PyMuPDF for figures) and skip the heavy table-structure model.
    pipeline_options.generate_page_images = False
    pipeline_options.generate_picture_images = False
    pipeline_options.do_table_structure = False
    _DOCLING_CONVERTER = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    return _DOCLING_CONVERTER


_DOCLING_CONVERTER = None


def _docling_markdown(pdf_path: Path, max_pages: int | None = None) -> str | None:
    """Convert a PDF to structured markdown via Docling. Returns None on failure.

    ``max_pages`` guards against memory blow-ups: above that page count Docling
    is skipped entirely (the caller should fall back to PyMuPDF).
    """
    limit = settings.docling_max_pages if max_pages is None else max_pages
    try:
        if limit and limit > 0:
            import fitz  # PyMuPDF

            with fitz.open(pdf_path) as _d:
                if _d.page_count > limit:
                    return None
        result = _docling_converter().convert(str(pdf_path))
        markdown = (result.document.export_to_markdown() or "").strip()
        return markdown or None
    except Exception:  # noqa: BLE001 - docling is optional; degrade gracefully
        return None


class DoclingExtractor(BaseExtractor):
    """Structured extraction via Docling (rich markdown, no embedded figures)."""

    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        markdown = _docling_markdown(pdf_path) or ""
        pages = [PageContent(page=1, text=markdown, source="docling")]
        return ExtractedDocument(
            filename=pdf_path.name, pages=pages, rich_markdown=markdown or None
        )


class HybridExtractor(BaseExtractor):
    """Recommended backend: Docling text + PyMuPDF figures + OCR fallback.

    PyMuPDF provides per-page text (with an OCR fallback for image-only pages)
    and the embedded figures; Docling, when available, supplies a richer,
    structured markdown that becomes the primary text fed to the model. If
    Docling is missing or fails, the result gracefully degrades to plain
    PyMuPDF output.
    """

    def __init__(self, render_dpi: int = 130, enable_ocr: bool = True) -> None:
        self._py = PyMuPDFExtractor(render_dpi=render_dpi, enable_ocr=enable_ocr)

    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        doc = self._py.extract(pdf_path, figures_dir)
        # Skip Docling on large PDFs: its layout models render every page and
        # run out of memory. PyMuPDF text is already in `doc`.
        max_pages = settings.docling_max_pages
        if max_pages and doc.n_pages > max_pages:
            return doc
        rich = _docling_markdown(pdf_path, max_pages=0)
        if rich:
            doc.rich_markdown = rich
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
