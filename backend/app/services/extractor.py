"""Pluggable PDF extraction.

A backend turns a PDF into a list of :class:`PageContent` (text + an optional
rendered image path). The default backend uses PyMuPDF; OCR, docling and
markitdown are optional and selected via configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings


@dataclass
class PageContent:
    page: int
    text: str
    image_path: str | None = None
    source: str = "pymupdf"


@dataclass
class ExtractedDocument:
    filename: str
    pages: list[PageContent] = field(default_factory=list)

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    def full_text(self) -> str:
        return "\n\n".join(
            f"===== PAGINA {p.page}/{self.n_pages} =====\n{p.text}" for p in self.pages
        )


class BaseExtractor:
    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        raise NotImplementedError


class PyMuPDFExtractor(BaseExtractor):
    """Default extractor: per-page text + rendered PNG, with optional OCR fallback."""

    def __init__(self, render_dpi: int = 130, enable_ocr: bool = False) -> None:
        self.render_dpi = render_dpi
        self.enable_ocr = enable_ocr

    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        import fitz  # PyMuPDF

        figures_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        zoom = self.render_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        pages: list[PageContent] = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_path = figures_dir / f"p{i:03d}.png"
            pix.save(img_path)

            source = "pymupdf"
            if self.enable_ocr and len(text) < 16:
                ocr_text = self._ocr(img_path)
                if ocr_text:
                    text = ocr_text
                    source = "ocr"

            pages.append(
                PageContent(page=i, text=text, image_path=str(img_path), source=source)
            )

        doc.close()
        return ExtractedDocument(filename=pdf_path.name, pages=pages)

    @staticmethod
    def _ocr(img_path: Path) -> str:
        try:
            import pytesseract  # type: ignore
            from PIL import Image

            return pytesseract.image_to_string(Image.open(img_path)).strip()
        except Exception:  # noqa: BLE001 - OCR is best-effort/optional
            return ""


class DoclingExtractor(BaseExtractor):
    """Optional structured extraction via docling (markdown per page)."""

    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        from docling.document_converter import DocumentConverter  # type: ignore

        converter = DocumentConverter()
        result = converter.convert(str(pdf_path))
        markdown = result.document.export_to_markdown()
        pages = [PageContent(page=1, text=markdown, source="docling")]
        return ExtractedDocument(filename=pdf_path.name, pages=pages)


class MarkItDownExtractor(BaseExtractor):
    """Optional simple conversion to markdown via markitdown."""

    def extract(self, pdf_path: Path, figures_dir: Path) -> ExtractedDocument:
        from markitdown import MarkItDown  # type: ignore

        md = MarkItDown()
        result = md.convert(str(pdf_path))
        pages = [PageContent(page=1, text=result.text_content, source="markitdown")]
        return ExtractedDocument(filename=pdf_path.name, pages=pages)


def get_extractor(backend: str | None = None) -> BaseExtractor:
    """Return an extractor instance for the configured (or requested) backend."""
    backend = (backend or settings.extractor_backend).lower()
    if backend == "docling":
        return DoclingExtractor()
    if backend == "markitdown":
        return MarkItDownExtractor()
    return PyMuPDFExtractor(render_dpi=settings.render_dpi, enable_ocr=settings.enable_ocr)
