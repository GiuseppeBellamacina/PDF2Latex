"""Writer agent: write the LaTeX body of a single section (fan-out)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.prompts import WRITER_SYSTEM
from app.agents.state import PlannedSection, WrittenSection
from app.agents.utils import call_llm, strip_latex_fences
from app.core.config import settings
from app.core.logging import get_logger
from app.services.text_cleaning import outline_terms, select_relevant_chunks

logger = get_logger("writer")

MAX_FEWSHOT_CHARS = 6000


def _fig_id(rel_path: str) -> str:
    """Stable figure identifier = file basename without extension."""
    return Path(rel_path).stem


def figure_latex(rel_path: str, caption: str) -> str:
    """Render a single figure with safe, bounded sizing.

    ``keepaspectratio`` plus an explicit ``width``/``height`` cap guarantees the
    image never overflows the text block nor blows up to full-page size, which
    is what happened with a bare ``width=0.8\\linewidth``. ``[htbp]`` lets LaTeX
    place the float sensibly instead of forcing it exactly in place (``[H]``),
    which produced large gaps and stranded images.
    """
    cap = caption.strip() or "Figura tratta dal materiale sorgente."
    w = settings.figure_width_ratio
    h = settings.figure_max_height_ratio
    return (
        "\\begin{figure}[htbp]\\centering\n"
        f"\\includegraphics[width={w:.2f}\\linewidth,"
        f"height={h:.2f}\\textheight,keepaspectratio]{{{rel_path}}}\n"
        f"\\caption{{{cap}}}\n"
        "\\end{figure}"
    )


# Backwards-compatible alias used internally.
def _figure_block(rel_path: str, caption: str) -> str:
    return figure_latex(rel_path, caption)


def _read_brace_arg(s: str, i: int) -> tuple[str, int]:
    """Read a ``{...}`` argument starting at ``s[i] == '{'`` with brace matching.

    Returns the inner content and the index just past the closing brace.
    """
    assert s[i] == "{"
    depth = 0
    start = i + 1
    j = i
    while j < len(s):
        c = s[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:j], j + 1
        j += 1
    return s[start:], len(s)  # unbalanced; take the rest


def expand_figrefs(
    latex: str,
    id_to_path: dict[str, str],
    mandatory_ids: list[str],
) -> str:
    """Deterministically turn ``\\figref{ID}{caption}`` into real figure blocks.

    IDs are resolved against the real extracted figures; unknown IDs are simply
    dropped (no hallucinated path can reach the document). Every mandatory
    figure is guaranteed: any not referenced by the model is appended at the
    end of the section.
    """
    out: list[str] = []
    used: set[str] = set()
    token = "\\figref"
    i = 0
    n = len(latex)
    while i < n:
        idx = latex.find(token, i)
        if idx == -1:
            out.append(latex[i:])
            break
        out.append(latex[i:idx])
        j = idx + len(token)
        while j < n and latex[j] in " \t":
            j += 1
        if j < n and latex[j] == "{":
            fid, j = _read_brace_arg(latex, j)
            caption = ""
            if j < n and latex[j] == "{":
                caption, j = _read_brace_arg(latex, j)
            path = id_to_path.get(fid.strip())
            if path:
                used.add(fid.strip())
                out.append(_figure_block(path, caption))
            # Unknown ID -> drop silently.
            i = j
        else:
            # Malformed \figref with no argument -> drop the token.
            i = j

    result = "".join(out)

    missing = [
        m for m in dict.fromkeys(mandatory_ids) if m not in used and m in id_to_path
    ]
    if missing:
        blocks = [_figure_block(id_to_path[m], "") for m in missing]
        result = result.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n"
    return result


async def write_section(
    section: PlannedSection,
    documents_by_name: dict[str, str],
    figures_by_name: dict[str, list[str]],
    assigned_mandatory: list[str],
    captions_by_path: dict[str, str],
    few_shot: str,
    language: str,
    llm_config: dict[str, Any],
) -> WrittenSection:
    """Generate the LaTeX body for one planned section.

    ``assigned_mandatory`` is the list of figure paths assigned to THIS section
    (each mandatory figure is assigned to exactly one section upstream, so no
    image is forced into multiple sections).
    """
    outline_json = json.dumps(section["outline"], ensure_ascii=False, indent=2)

    # Relevance-based source selection (instead of blind truncation): rank the
    # source passages by overlap with the section title + outline and keep the
    # most relevant ones up to the budget.
    terms = outline_terms(section["title"], section.get("outline", {}))
    source_text = ""
    figures: list[str] = []
    n_sources = len(section["source_filenames"]) or 1
    per_source_budget = max(2000, settings.writer_source_chars // n_sources)
    for fname in section["source_filenames"]:
        chunk = documents_by_name.get(fname, "")
        if chunk:
            selected = select_relevant_chunks(chunk, terms, per_source_budget)
            source_text += f"\n--- {fname} ---\n{selected}\n"
        figures.extend(figures_by_name.get(fname, []))

    # Cap how many mandatory figures land in a single section so a slide-heavy
    # source cannot flood it; the rest were assigned to other sections upstream.
    mandatory = list(dict.fromkeys(assigned_mandatory))[
        : settings.max_figures_per_section
    ]

    # Deterministic figure registry: ID -> real relative path.
    id_to_path: dict[str, str] = {}
    for rel in figures:
        id_to_path.setdefault(_fig_id(rel), rel)
    for rel in mandatory:
        id_to_path.setdefault(_fig_id(rel), rel)
    mandatory_ids = [_fig_id(rel) for rel in dict.fromkeys(mandatory)]

    def _label(fid: str) -> str:
        cap = (captions_by_path.get(id_to_path.get(fid, ""), "") or "").strip()
        return f"{fid} — {cap}" if cap else fid

    fewshot_part = (
        f"\n\nEsempio di stile LaTeX desiderato:\n{few_shot[:MAX_FEWSHOT_CHARS]}"
        if few_shot
        else ""
    )

    figures_part = ""
    optional_ids = [
        fid for fid in (_fig_id(f) for f in figures) if fid not in set(mandatory_ids)
    ]
    optional_ids = list(dict.fromkeys(optional_ids))[: settings.max_figures_per_section]
    if mandatory_ids:
        listed = "\n".join(f"- {_label(fid)}" for fid in mandatory_ids)
        figures_part += (
            "\n\nFigure OBBLIGATORIE: inseriscile TUTTE con \\figref{ID}{didascalia} "
            "(una per riga). L'ID è prima del trattino; dopo il trattino c'è una "
            "descrizione del contenuto (da OCR) utile a scrivere una didascalia "
            "pertinente:\n" + listed
        )
    if optional_ids:
        listed = "\n".join(f"- {_label(fid)}" for fid in optional_ids)
        figures_part += (
            "\n\nFigure disponibili (facoltative, usa \\figref{ID}{didascalia} solo se "
            "pertinenti; la descrizione dopo il trattino aiuta a capire il "
            "contenuto):\n" + listed
        )

    user = (
        f"Lingua: {language}\n"
        f"Parte: {section['part_title']}\n"
        f"Titolo sezione: {section['title']}\n\n"
        f"Outline:\n{outline_json}\n\n"
        f"Materiale sorgente:\n{source_text}"
        f"{figures_part}"
        f"{fewshot_part}"
    )

    raw = await call_llm(
        llm_config,
        WRITER_SYSTEM,
        user,
        temperature=settings.writer_temperature,
        label=f"write:{section['title'][:40]}",
    )
    latex = strip_latex_fences(raw)
    latex = expand_figrefs(latex, id_to_path, mandatory_ids)
    logger.info(
        "Sezione scritta: '%s' (%d caratteri, %d figure obbligatorie)",
        section["title"],
        len(latex),
        len(mandatory_ids),
    )

    return WrittenSection(
        title=section["title"],
        part_title=section["part_title"],
        order_index=section["order_index"],
        latex=latex,
    )
