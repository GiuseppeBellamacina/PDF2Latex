"""Judge agent: evaluate the overall quality of the compiled document.

After a successful compile, the judge inspects the document critically. Two
complementary sources feed it:

* a **deterministic layout inspector** (no LLM, no multimodal model) that
  measures the compiled PDF — oversized or clustered figures, near-empty pages —
  and parses the pdflatex log for overfull/underfull boxes (text spilling into
  the margins). This works with any provider and is the default critique source.
* an **optional vision review**: when a vision-capable model is available and
  enabled, the PDF pages are rendered and shown to the model. Off by default.

The text judge combines the layout report with the LaTeX source and returns
concrete issues; :func:`revise_structure` then produces a corrected document
that is re-linted and re-compiled by the review stage.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from app.agents.prompts import (
    JUDGE_REVISE_SYSTEM,
    JUDGE_SYSTEM,
    JUDGE_VISION_SYSTEM,
)
from app.agents.schemas import JudgeSchema
from app.agents.utils import (
    call_llm,
    call_llm_structured,
    call_vision_structured,
    strip_latex_fences,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("judge")

MAX_DOC_CHARS = 48000


def _inspect_layout(pdf_path: str | None, compile_log: str | None) -> list[str]:
    """Measure concrete layout/figure problems without any LLM or vision model.

    Combines pdflatex log warnings (text overflowing the margins) with geometric
    measurements of the compiled PDF (figures that fill a page, pages that are
    nearly empty, pages crammed with images). Returns a short list of concrete,
    actionable observations the text judge can act on.
    """
    issues: list[str] = []

    # 1) pdflatex log: overfull boxes = content spilling out of the text block
    #    (typically too-wide figures, tables or math).
    if compile_log:
        overfull_h = len(re.findall(r"Overfull \\hbox", compile_log))
        overfull_v = len(re.findall(r"Overfull \\vbox", compile_log))
        if overfull_h >= 6:
            issues.append(
                f"{overfull_h} righe sforano nel margine (overfull hbox): "
                "alcune figure/tabelle/formule sono troppo larghe, riducine la "
                "larghezza."
            )
        if overfull_v >= 3:
            issues.append(
                f"{overfull_v} blocchi sforano in altezza (overfull vbox): "
                "contenuto troppo alto in pagina, riduci le figure o spezza il "
                "contenuto."
            )

    # 2) PDF geometry.
    if not pdf_path or not Path(pdf_path).exists():
        return issues
    try:
        import fitz  # PyMuPDF
    except Exception:  # noqa: BLE001 - no measurer available
        return issues

    big_pages: list[int] = []
    empty_pages: list[int] = []
    crammed_pages: list[int] = []
    try:
        with fitz.open(pdf_path) as doc:
            total = doc.page_count
            for i in range(total):
                page = doc.load_page(i)
                page_area = abs(page.rect.width * page.rect.height) or 1.0
                try:
                    infos = page.get_image_info(xrefs=False)
                except Exception:  # noqa: BLE001 - older PyMuPDF signature
                    infos = page.get_image_info()
                max_cov = 0.0
                for info in infos:
                    bbox = info.get("bbox")
                    if not bbox:
                        continue
                    w = abs(bbox[2] - bbox[0])
                    h = abs(bbox[3] - bbox[1])
                    max_cov = max(max_cov, (w * h) / page_area)
                text_len = len(page.get_text("text").strip())
                n_imgs = len(infos)

                if max_cov >= 0.80 and i >= 1:
                    big_pages.append(i + 1)
                elif text_len < 60 and n_imgs == 0 and 1 < i < total - 1:
                    empty_pages.append(i + 1)
                if n_imgs >= 5:
                    crammed_pages.append(i + 1)
    except Exception as exc:  # noqa: BLE001 - inspection is best-effort
        logger.debug("Ispezione layout fallita: %s", exc)
        return issues

    def _fmt(pages: list[int], limit: int = 6) -> str:
        head = ", ".join(str(p) for p in pages[:limit])
        return head + ("…" if len(pages) > limit else "")

    if big_pages:
        issues.append(
            "Figure troppo grandi: occupano quasi un'intera pagina "
            f"(pagine {_fmt(big_pages)}). Riduci width/height."
        )
    if crammed_pages:
        issues.append(
            f"Figure ammassate sulla stessa pagina (pagine {_fmt(crammed_pages)}): "
            "distribuiscile o rimuovi quelle ridondanti."
        )
    if empty_pages:
        issues.append(
            f"Pagine quasi vuote (pagine {_fmt(empty_pages)}): spazi bianchi "
            "eccessivi, rivedi la collocazione di figure e interruzioni."
        )
    return issues


def _merge_layout_issues(verdict: JudgeSchema, layout_issues: list[str]) -> JudgeSchema:
    """Make sure measured layout problems are acted on even if the LLM omits them."""
    if not layout_issues:
        return verdict
    existing = {i.strip().lower() for i in verdict.issues}
    for li in layout_issues:
        if li.strip().lower() not in existing:
            verdict.issues.append(li)
    # Measured defects mean the document isn't perfect: don't approve while
    # concrete problems remain.
    if verdict.issues:
        verdict.approved = False
    return verdict


def _render_pdf_pages(pdf_path: Path, out_dir: Path) -> list[Path]:
    """Render the PDF's pages to PNGs (capped) for the vision judge."""
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # noqa: BLE001 - no renderer, skip vision
        logger.debug("PyMuPDF non disponibile per il giudizio visivo: %s", exc)
        return []

    images: list[Path] = []
    zoom = settings.judge_vision_dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    try:
        with fitz.open(pdf_path) as doc:
            n = min(doc.page_count, settings.judge_vision_max_pages)
            for i in range(n):
                pix = doc.load_page(i).get_pixmap(matrix=matrix, alpha=False)
                out = out_dir / f"judge_p{i + 1:03d}.png"
                pix.save(out)
                images.append(out)
    except Exception as exc:  # noqa: BLE001 - rendering is best-effort
        logger.warning("Render PDF per il giudice fallito: %s", exc)
        return []
    return images


async def judge_structure(
    full_latex: str,
    llm_config: dict[str, Any],
    pdf_path: str | None = None,
    compile_log: str | None = None,
) -> JudgeSchema:
    """Return a critical verdict on the compiled document.

    Uses a deterministic layout report (figure sizing/placement, overflow, blank
    pages) by default; optionally also shows the rendered pages to a vision
    model when one is configured. Both feed concrete, actionable issues.
    """
    layout_issues: list[str] = []
    if settings.judge_layout_inspect:
        layout_issues = _inspect_layout(pdf_path, compile_log)
        if layout_issues:
            logger.info(
                "Judge: ispezione layout -> %d osservazioni", len(layout_issues)
            )

    layout_report = ""
    if layout_issues:
        layout_report = (
            "\n\n=== REPORT TECNICO DEL LAYOUT (misurato sul PDF) ===\n"
            + "\n".join(f"- {i}" for i in layout_issues)
        )

    # Optional vision review of the actual rendered pages.
    if settings.judge_vision and pdf_path and Path(pdf_path).exists():
        with tempfile.TemporaryDirectory(prefix="judge_") as tmp:
            images = _render_pdf_pages(Path(pdf_path), Path(tmp))
            if images:
                user = (
                    "Queste sono le pagine del PDF compilato, in ordine. "
                    "Guardale e valuta il documento, poi restituisci il verdetto "
                    "JSON." + layout_report
                )
                verdict = await call_vision_structured(
                    llm_config,
                    JUDGE_VISION_SYSTEM,
                    user,
                    images=images,
                    schema=JudgeSchema,
                    temperature=settings.judge_temperature,
                    label="judge-vision",
                )
                if verdict is not None:
                    verdict = _merge_layout_issues(verdict, layout_issues)
                    logger.info(
                        "Judge (visivo, %d pagine): approved=%s score=%s issues=%d",
                        len(images),
                        verdict.approved,
                        verdict.score,
                        len(verdict.issues),
                    )
                    return verdict
                logger.info("Judge: vision non disponibile, uso revisione testuale")

    # Text review (default path): LaTeX source + measured layout report.
    user = (
        "Valuta la qualità complessiva del seguente documento LaTeX (struttura e "
        "layout) e restituisci il verdetto JSON. Tieni conto del report tecnico "
        "del layout se presente.\n\n"
        f"{full_latex[:MAX_DOC_CHARS]}"
        f"{layout_report}"
    )
    verdict = await call_llm_structured(
        llm_config,
        JUDGE_SYSTEM,
        user,
        schema=JudgeSchema,
        temperature=settings.judge_temperature,
        label="judge",
    )
    verdict = _merge_layout_issues(verdict, layout_issues)
    logger.info(
        "Judge (testuale): approved=%s score=%s issues=%d",
        verdict.approved,
        verdict.score,
        len(verdict.issues),
    )
    return verdict


async def revise_structure(
    full_latex: str,
    issues: list[str],
    llm_config: dict[str, Any],
) -> str:
    """Reorganise the document to resolve the structural issues found."""
    issue_list = "\n".join(f"- {i}" for i in issues) or "- migliora la struttura"
    user = (
        "Risolvi i seguenti problemi STRUTTURALI nel documento LaTeX e "
        "restituisci il documento completo corretto.\n\n"
        f"=== PROBLEMI ===\n{issue_list}\n\n"
        f"=== DOCUMENTO ===\n{full_latex[:MAX_DOC_CHARS]}"
    )
    raw = await call_llm(
        llm_config,
        JUDGE_REVISE_SYSTEM,
        user,
        temperature=settings.judge_temperature,
        label="judge-revise",
    )
    logger.info("Judge: revisione strutturale applicata (%d problemi)", len(issues))
    return strip_latex_fences(raw)
