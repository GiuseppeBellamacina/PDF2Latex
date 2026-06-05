"""Text post-processing helpers for extracted PDF content.

Two concerns live here, both deterministic (no LLM calls):

1. :func:`strip_recurring_lines` removes running headers/footers and page
   numbers that repeat across most pages. These add noise, waste the model's
   context budget and confuse the analysis.
2. :func:`select_relevant_chunks` picks the source passages most relevant to a
   given section outline instead of blindly truncating to the first N
   characters. It uses simple lexical overlap scoring, so it needs no model or
   embedding service.
"""

from __future__ import annotations

import re
from collections import Counter

_PAGE_MARKER_RE = re.compile(r"=====\s*PAGINA\s*\d+.*?=====", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-zA-ZàèéìòùÀÈÉÌÒÙ0-9]{3,}")

# Italian + English stopwords that should not drive relevance scoring.
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "was",
    "were",
    "del",
    "della",
    "delle",
    "dei",
    "degli",
    "una",
    "uno",
    "che",
    "per",
    "con",
    "sono",
    "come",
    "alla",
    "allo",
    "agli",
    "nel",
    "nella",
    "nelle",
    "dei",
    "gli",
    "non",
    "più",
    "anche",
    "questo",
    "questa",
    "essere",
    "viene",
    "tra",
    "fra",
    "sul",
    "sulla",
    "loro",
    "suo",
    "sua",
    "può",
    "deve",
}


def _normalize_line(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def strip_recurring_lines(
    pages: list[str], min_ratio: float = 0.6, min_pages: int = 4
) -> list[str]:
    """Remove lines that recur (as headers/footers) on most pages.

    ``pages`` is a list of per-page text blocks. A line that appears on at
    least ``min_ratio`` of the pages is considered chrome (running title, page
    number, watermark) and dropped. Pure page-number lines are always dropped.
    Returns the cleaned pages in the same order. No-op for short documents.
    """
    n = len(pages)
    if n < min_pages:
        return pages

    counts: Counter[str] = Counter()
    for text in pages:
        seen: set[str] = set()
        for raw in text.splitlines():
            norm = _normalize_line(raw)
            if norm and norm not in seen:
                seen.add(norm)
                counts[norm] += 1

    threshold = max(2, int(n * min_ratio))
    recurring = {norm for norm, c in counts.items() if c >= threshold}

    cleaned: list[str] = []
    for text in pages:
        kept: list[str] = []
        for raw in text.splitlines():
            norm = _normalize_line(raw)
            if not norm:
                kept.append(raw)
                continue
            if norm in recurring:
                continue
            # Drop standalone page numbers / "Pag. 3 di 10".
            if re.fullmatch(r"#|pag\.?\s*#(\s*(di|/)\s*#)?", norm):
                continue
            kept.append(raw)
        cleaned.append("\n".join(kept))
    return cleaned


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text) if t.lower() not in _STOPWORDS]


def split_into_chunks(text: str, target_chars: int) -> list[str]:
    """Split text into chunks of roughly ``target_chars``, on page/para breaks.

    Prefers splitting on the ``===== PAGINA n =====`` markers (when present),
    then on blank lines, so a chunk stays semantically coherent.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]

    # Prefer page markers as natural boundaries.
    segments = _PAGE_MARKER_RE.split(text)
    markers = _PAGE_MARKER_RE.findall(text)
    if len(segments) > 1:
        # Re-attach each marker to its segment for context.
        rebuilt: list[str] = []
        # segments[0] is the preamble before the first marker.
        if segments[0].strip():
            rebuilt.append(segments[0].strip())
        for marker, seg in zip(markers, segments[1:]):
            rebuilt.append(f"{marker}\n{seg.strip()}")
        units = rebuilt
    else:
        units = [p for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + len(unit) + 2 <= target_chars:
            current += "\n\n" + unit
        else:
            chunks.append(current)
            current = unit
        # A single oversized unit must still be broken up hard.
        while len(current) > target_chars:
            chunks.append(current[:target_chars])
            current = current[target_chars:]
    if current.strip():
        chunks.append(current)
    return chunks


def select_relevant_chunks(
    text: str, query_terms: list[str], budget_chars: int, chunk_chars: int = 3000
) -> str:
    """Return the passages of ``text`` most relevant to ``query_terms``.

    Splits ``text`` into chunks, scores each by lexical overlap with the query
    terms (section title + outline points), and greedily fills the character
    budget with the highest-scoring chunks while preserving reading order. This
    replaces a naive ``text[:budget]`` truncation that may miss the content a
    section actually needs.
    """
    text = text.strip()
    if not text:
        return ""
    if len(text) <= budget_chars:
        return text

    query = Counter(t for t in (w.lower() for w in query_terms) if t not in _STOPWORDS)
    chunks = split_into_chunks(text, chunk_chars)
    if not query:
        # No query signal: keep the leading passages up to the budget.
        out, total = [], 0
        for ch in chunks:
            if total + len(ch) > budget_chars:
                break
            out.append(ch)
            total += len(ch)
        return "\n\n".join(out) or text[:budget_chars]

    scored: list[tuple[float, int, str]] = []
    for idx, ch in enumerate(chunks):
        toks = _tokens(ch)
        if not toks:
            scored.append((0.0, idx, ch))
            continue
        freq = Counter(toks)
        overlap = sum(freq[q] * w for q, w in query.items())
        score = overlap / (len(toks) ** 0.5)  # length-normalised
        scored.append((score, idx, ch))

    # Pick highest-scoring chunks until the budget is full, then restore order.
    scored.sort(key=lambda x: x[0], reverse=True)
    chosen: list[tuple[int, str]] = []
    total = 0
    for score, idx, ch in scored:
        if total + len(ch) > budget_chars and chosen:
            continue
        chosen.append((idx, ch))
        total += len(ch)
        if total >= budget_chars:
            break
    chosen.sort(key=lambda x: x[0])
    return "\n\n".join(ch for _, ch in chosen)


def outline_terms(title: str, outline: dict) -> list[str]:
    """Flatten a section title + outline dict into a list of query terms."""
    terms: list[str] = _tokens(title)
    if isinstance(outline, dict):
        for value in outline.values():
            if isinstance(value, list):
                for item in value:
                    terms.extend(_tokens(str(item)))
            elif isinstance(value, str):
                terms.extend(_tokens(value))
    return terms
