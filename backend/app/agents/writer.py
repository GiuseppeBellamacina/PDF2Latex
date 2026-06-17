"""Writer agent: write the LaTeX body of a single section with progressive
context, knowledge supplementation, and iterative expansion for short sections."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.agents.prompts import (
    WRITER_CONTEXT_SUMMARIZE_SYSTEM,
    WRITER_EXPAND_SYSTEM,
    WRITER_KNOWLEDGE_INSTRUCTION,
    WRITER_NO_KNOWLEDGE_INSTRUCTION,
    WRITER_SYSTEM,
)
from app.agents.state import PlannedSection, WrittenSection
from app.agents.utils import call_llm, strip_latex_fences
from app.core.config import settings
from app.core.logging import get_logger
from app.services.bibliography import strip_inline_bibliography, strip_unknown_citations
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
    id_to_caption: dict[str, str] | None = None,
) -> str:
    """Deterministically turn ``\\figref{ID}{caption}`` into real figure blocks.

    IDs are resolved against the real extracted figures; unknown IDs are simply
    dropped (no hallucinated path can reach the document). Every mandatory
    figure is guaranteed: any not referenced by the model is appended at the
    end of the section. When a real caption was extracted from the source PDF
    for a figure, it OVERRIDES the model-written caption: the caption is bound
    to the image deterministically, so figures and captions can never be
    swapped or mismatched.
    """
    id_to_caption = id_to_caption or {}
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
            key = fid.strip()
            path = id_to_path.get(key)
            if path:
                used.add(key)
                # Real PDF caption wins; fall back to the model's caption.
                final_caption = id_to_caption.get(key, "").strip() or caption
                out.append(_figure_block(path, final_caption))
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
        blocks = [
            _figure_block(id_to_path[m], id_to_caption.get(m, "")) for m in missing
        ]
        result = result.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n"
    return result


def _build_context_part(context: list[str] | None) -> str:
    """Format the accumulated context facts as a prompt for the writer."""
    if not context:
        return ""
    items = "\n".join(f"  - {fact}" for fact in context)
    return (
        "\n\nCONCETTI GIÀ TRATTATI nelle sezioni precedenti di questo capitolo "
        "(NON ridefinirli, ma puoi farvi riferimento):\n" + items
    )


async def write_section(
    section: PlannedSection,
    documents_by_name: dict[str, str],
    assigned_mandatory: list[str],
    captions_by_path: dict[str, str],
    few_shot: str,
    language: str,
    llm_config: dict[str, Any],
    available_refs: list[dict[str, str]] | None = None,
    writer_context: list[str] | None = None,
    use_knowledge: bool = False,
    user_sources_context: str = "",
) -> WrittenSection:
    """Generate the LaTeX body for one planned section.

    ``assigned_mandatory`` is the list of user-selected figure paths assigned to
    THIS section (each selected figure is assigned to exactly one section
    upstream). ONLY these figures may appear: unselected figures are never
    offered to the model and never reach the document. ``captions_by_path`` maps
    a figure path to the real caption extracted from the source PDF; when set it
    is bound to the figure and overrides whatever caption the model writes.
    ``available_refs`` are the bibliographic references (with citation ``key``)
    drawn from this section's sources, offered to the model so it can insert
    ``\\cite{key}`` where genuinely relevant.

    ``writer_context`` is a list of key facts already covered in previous
    sections of the same chapter; the writer is instructed to avoid repeating
    them and instead build upon them.

    ``use_knowledge`` allows the writer to supplement with its own knowledge
    when source material is insufficient on a topic.

    ``user_sources_context`` is a pre-formatted block describing the user's
    bibliographic sources (authors, title, year, venue). The writer can draw
    on its knowledge of these works to cite them and enrich the content even
    without having the full source text.
    """
    outline_json = json.dumps(section["outline"], ensure_ascii=False, indent=2)

    # Relevance-based source selection: rank source passages by overlap with
    # the section title + outline and keep the most relevant ones. Instead of
    # splitting a fixed budget across sources (which shrinks with many sources),
    # each source gets the full per-section budget, capped at the generous
    # ``writer_max_source_chars`` total.
    terms = outline_terms(section["title"], section.get("outline", {}))
    budget = settings.writer_source_chars
    max_total = settings.writer_max_source_chars
    source_text = ""
    total_chars = 0
    for fname in section["source_filenames"]:
        chunk = documents_by_name.get(fname, "")
        if chunk:
            selected_src = select_relevant_chunks(chunk, terms, budget)
            source_text += f"\n--- {fname} ---\n{selected_src}\n"
            total_chars += len(selected_src)
            if max_total and total_chars >= max_total:
                break

    # ONLY the user-selected figures assigned to this section may be used. Cap
    # per section so a slide-heavy source cannot flood it; any selected figure
    # left over is appended elsewhere by the pipeline's safety net.
    selected = list(dict.fromkeys(assigned_mandatory))[
        : settings.max_figures_per_section
    ]
    id_to_path: dict[str, str] = {}
    id_to_caption: dict[str, str] = {}
    for rel in selected:
        fid = _fig_id(rel)
        id_to_path.setdefault(fid, rel)
        real_cap = (captions_by_path.get(rel) or "").strip()
        if real_cap:
            id_to_caption.setdefault(fid, real_cap)
    mandatory_ids = [_fig_id(rel) for rel in dict.fromkeys(selected)]

    fewshot_part = (
        f"\n\nEsempio di stile LaTeX desiderato:\n{few_shot[:MAX_FEWSHOT_CHARS]}"
        if few_shot
        else ""
    )

    figures_part = ""
    if mandatory_ids:
        lines = []
        for fid in mandatory_ids:
            hint = id_to_caption.get(fid)
            lines.append(f"- {fid}" + (f" (didascalia reale: {hint})" if hint else ""))
        listed = "\n".join(lines)
        figures_part = (
            "\n\nFIGURE DA INSERIRE (solo queste, scelte dall'utente): inserisci "
            "TUTTE e SOLO queste figure, ciascuna con \\figref{ID}{didascalia} su "
            "una riga a sé, collocandola nel punto del testo più pertinente. "
            "Quando è indicata una 'didascalia reale' usala come didascalia "
            "(verrà comunque applicata automaticamente); altrimenti scrivi una "
            "didascalia BREVE e coerente con il testo in quel punto. NON inserire "
            "nessun'altra figura e non inventare ID.\n" + listed
        )

    refs = available_refs or []
    known_keys = {r["key"] for r in refs if r.get("key")}
    refs_part = ""
    if refs:
        ref_lines = []
        for r in refs:
            descr = ", ".join(
                x for x in (r.get("authors"), r.get("title"), r.get("year")) if x
            )
            ref_lines.append(f"- {r['key']}: {descr}")
        refs_part = (
            "\n\nRIFERIMENTI CITABILI (usa \\cite{chiave} solo dove pertinente, "
            "solo queste chiavi):\n" + "\n".join(ref_lines)
        )

    # Build the contextual instruction about previous sections.
    context_part = _build_context_part(writer_context)

    # User-provided sources context — lets the writer "read" and cite them.
    user_src_part = user_sources_context if user_sources_context else ""

    # Knowledge instruction.
    knowledge_instruction = (
        WRITER_KNOWLEDGE_INSTRUCTION
        if use_knowledge
        else WRITER_NO_KNOWLEDGE_INSTRUCTION
    )

    # Use .replace() rather than .format() because WRITER_SYSTEM contains
    # LaTeX curly braces (e.g. \section{...}) that .format() would misinterpret.
    system_prompt = WRITER_SYSTEM.replace(
        "{knowledge_instruction}", knowledge_instruction
    )

    user = (
        f"Lingua: {language}\n"
        f"Parte: {section['part_title']}\n"
        f"Titolo sezione: {section['title']}\n\n"
        f"Outline:\n{outline_json}\n\n"
        f"Materiale sorgente:\n{source_text}"
        f"{context_part}"
        f"{user_src_part}"
        f"{figures_part}"
        f"{refs_part}"
        f"{fewshot_part}"
    )

    raw = await call_llm(
        llm_config,
        system_prompt,
        user,
        temperature=settings.writer_temperature,
        label=f"write:{section['title'][:40]}",
    )
    latex = strip_latex_fences(raw)
    latex = expand_figrefs(latex, id_to_path, mandatory_ids, id_to_caption)
    # Drop any bibliography the model added inline and any citation to a key it
    # was not offered, so only the single end-of-document bibliography remains.
    latex = strip_inline_bibliography(latex)
    latex = strip_unknown_citations(latex, known_keys)
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
        outline=section.get("outline", {}),
        source_filenames=list(section.get("source_filenames", [])),
    )


async def expand_section(
    section: WrittenSection,
    documents_by_name: dict[str, str],
    language: str,
    llm_config: dict[str, Any],
) -> WrittenSection:
    """Expand a section that is too short with more detail from the source material.

    Only triggers when the section's LaTeX body is below
    ``settings.writer_expand_threshold`` characters. The original content is
    preserved; new text is added where the LLM sees gaps.
    """
    latex = section["latex"]
    section_title = section["title"]

    # Gather source text for the expansion (same files as the original).
    terms = outline_terms(section_title, section.get("outline", {}))
    source_text = ""
    budget = settings.writer_source_chars
    for fname in section.get("source_filenames", []):
        chunk = documents_by_name.get(fname, "")
        if chunk:
            selected_src = select_relevant_chunks(chunk, terms, budget)
            source_text += f"\n--- {fname} ---\n{selected_src}\n"

    user = (
        f"Lingua: {language}\n"
        f"Titolo sezione: {section_title}\n\n"
        f"Materiale sorgente (per aggiungere dettagli):\n{source_text}\n\n"
        f"SEZIONE ATTUALE DA ESPANDERE:\n\n{latex}"
    )

    raw = await call_llm(
        llm_config,
        WRITER_EXPAND_SYSTEM,
        user,
        temperature=settings.writer_temperature,
        label=f"expand:{section_title[:40]}",
    )
    expanded = strip_latex_fences(raw)
    logger.info(
        "Sezione espansa: '%s' (%d → %d caratteri)",
        section_title,
        len(latex),
        len(expanded),
    )
    return WrittenSection(
        title=section["title"],
        part_title=section["part_title"],
        order_index=section["order_index"],
        latex=expanded,
        outline=section.get("outline", {}),
        source_filenames=list(section.get("source_filenames", [])),
    )


async def summarize_section_context(
    section: WrittenSection,
    llm_config: dict[str, Any],
) -> list[str]:
    """Extract 3-5 key facts/concepts from a written section for context sharing.

    These facts are passed to subsequent sections in the same chapter so they
    can avoid repetition and build on established concepts.
    """
    latex = section["latex"]
    # Strip LaTeX markup to reduce noise for the summarizer — keep only
    # content-bearing text.  A very light pass: drop commands, keep their
    # arguments (which carry the content).
    text = latex
    # If the section is too short, skip context extraction (already a short
    # section will get expanded later).
    if len(text) < 200:
        return []

    user = f"Contenuto LaTeX della sezione '{section['title']}':\n\n{text}"

    try:
        raw = await call_llm(
            llm_config,
            WRITER_CONTEXT_SUMMARIZE_SYSTEM,
            user,
            temperature=0.0,
            label=f"context:{section['title'][:40]}",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort context extraction
        logger.debug("Estrazione contesto fallita per '%s': %s", section["title"], exc)
        return []

    # Parse the JSON array response.

    cleaned = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        facts = json.loads(cleaned)
        if isinstance(facts, list):
            return [str(f) for f in facts if str(f).strip()][:5]
    except json.JSONDecodeError:
        logger.debug(
            "JSON contesto non valido per '%s': %s", section["title"], raw[:200]
        )
    return []
