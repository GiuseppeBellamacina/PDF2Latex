"""Isolated Docling worker (run as a subprocess).

Docling loads heavy ML layout/table models and, on large PDFs, can exhaust
memory (``std::bad_alloc``). To keep the main server stable we never run it
in-process: the extractor slices a PDF into small page-range chunks and invokes
this module once per chunk via ``python -m app.services.docling_worker``. When
the subprocess exits, the OS reclaims all the memory it used.

Usage::

    python -m app.services.docling_worker <pdf_path> <out_markdown_path> [--tables]

The converted markdown is written to ``out_markdown_path`` (UTF-8). Status and
errors go to stderr; the process exits 0 on success, non-zero on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path


def convert(pdf_path: Path, enable_tables: bool) -> str:
    """Convert a (small) PDF to markdown via Docling with its OCR disabled."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    # We run our own OCR (PyMuPDF + pytesseract); Docling's RapidOCR/ONNX is
    # redundant and memory-hungry, so keep it off here.
    pipeline_options.do_ocr = False
    pipeline_options.generate_page_images = False
    pipeline_options.generate_picture_images = False
    # Tables carry a lot of value in technical/academic docs. Enabled by
    # default, but on isolated small chunks so the memory cost stays bounded.
    pipeline_options.do_table_structure = enable_tables

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(str(pdf_path))
    return (result.document.export_to_markdown() or "").strip()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: docling_worker <pdf> <out_md> [--tables]", file=sys.stderr)
        return 2

    pdf_path = Path(argv[0])
    out_path = Path(argv[1])
    enable_tables = "--tables" in argv[2:]

    try:
        markdown = convert(pdf_path, enable_tables)
    except Exception as exc:  # noqa: BLE001 - report and let caller fall back
        print(f"docling_worker failed: {exc}", file=sys.stderr)
        return 1

    try:
        out_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        print(f"docling_worker could not write output: {exc}", file=sys.stderr)
        return 1

    print(f"docling_worker ok: {len(markdown)} chars", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
