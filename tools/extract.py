"""Estrae testo (per pagina) e immagini chiave (slide renderizzate) dai PDF.

Uso:
    python tools/extract.py

Richiede PyMuPDF (pymupdf). Genera:
    build/extracted/<nome>.txt   -> testo per pagina
    figures/<nome>/pXX.png       -> render di ogni slide (per scegliere le figure)
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "build" / "extracted"
FIG_DIR = ROOT / "figures"

# DPI per il render delle slide (zoom = dpi/72).
RENDER_DPI = 130


def slug(name: str) -> str:
    return name.replace(".pdf", "")


def extract_pdf(pdf_path: Path) -> None:
    name = slug(pdf_path.name)
    print(f"\n=== {pdf_path.name} ===")
    doc = fitz.open(pdf_path)

    # --- Testo per pagina ---
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    out_txt = EXTRACT_DIR / f"{name}.txt"
    parts: list[str] = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        parts.append(f"\n\n===== PAGINA {i}/{doc.page_count} =====\n{text}")
    out_txt.write_text("".join(parts), encoding="utf-8")
    print(f"  testo  -> {out_txt.relative_to(ROOT)} ({len(parts)} pagine)")

    # --- Render di ogni slide come PNG ---
    fig_sub = FIG_DIR / name
    fig_sub.mkdir(parents=True, exist_ok=True)
    zoom = RENDER_DPI / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        out_png = fig_sub / f"p{i:03d}.png"
        pix.save(out_png)
    print(f"  figure -> {fig_sub.relative_to(ROOT)}/ ({doc.page_count} render)")

    doc.close()


def main() -> int:
    pdfs = sorted(ROOT.glob("*.pdf"))
    if not pdfs:
        print("Nessun PDF trovato nella root del workspace.")
        return 1
    for pdf in pdfs:
        extract_pdf(pdf)
    print("\nFatto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
