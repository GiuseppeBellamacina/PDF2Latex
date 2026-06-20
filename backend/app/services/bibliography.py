"""Bibliography handling: consolidate references and build a BibTeX database.

References are extracted from each source PDF by the analyzer. Here they are
de-duplicated, given stable citation keys and rendered as BibTeX entries. The
writer inserts ``\\cite{key}`` where a reference is actually used; at assembly
time only the cited entries are kept, so the final bibliography lists exactly
what the document cites — placed once, at the end (``\\bibliography{references}``).

Everything here is deterministic (no LLM): cheaper and far more reliable than
asking a model to format BibTeX.
"""

from __future__ import annotations

import re
from typing import Any

# A reference as carried through the pipeline / stored in ``references_pool``:
#   {key, source_filename, authors, title, year, venue, url?}
Reference = dict[str, str]


_KEY_CLEAN_RE = re.compile(r"[^a-z0-9]+")
# \cite, \citep, \citet, \parencite, \textcite ... with an optional [..] option
# and one or more comma-separated keys.
_CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|citeauthor|citeyear|parencite|textcite|autocite)\b"
    r"(?:\[[^\]]*\])?\s*\{([^}]*)\}"
)
_THEBIB_RE = re.compile(
    r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.DOTALL
)
_BIB_CMD_RE = re.compile(
    r"\\(?:bibliographystyle|bibliography|printbibliography|addbibresource|nocite)"
    r"(?:\[[^\]]*\])?\s*(?:\{[^}]*\})?"
)


def _first_author_surname(authors: str) -> str:
    """Best-effort surname of the first author from a free-form author string."""
    authors = (authors or "").strip()
    if not authors:
        return ""
    # Split on the usual author separators.
    first = re.split(r"\s+and\s+|;|,", authors)[0].strip()
    if not first:
        return ""
    # "Surname, Given" already gives the surname first; otherwise take the last
    # whitespace-separated token as the surname.
    if "," in authors.split(" and ")[0]:
        surname = first
    else:
        surname = first.split()[-1] if first.split() else first
    return surname


def _slug(text: str, limit: int = 24) -> str:
    return _KEY_CLEAN_RE.sub("", (text or "").lower())[:limit]


def make_key(ref: Reference, used: set[str]) -> str:
    """Build a stable, unique BibTeX key from author + year (+ title fallback)."""
    surname = _slug(_first_author_surname(ref.get("authors", "")), 16)
    year = re.sub(r"\D", "", ref.get("year", ""))[:4]
    base = (surname or _slug(ref.get("title", ""), 16) or "ref") + (year or "")
    base = base or "ref"
    key = base
    suffix = ord("a")
    while key in used:
        key = f"{base}{chr(suffix)}"
        suffix += 1
    used.add(key)
    return key


def _norm(text: str) -> str:
    return _KEY_CLEAN_RE.sub("", (text or "").lower())


def consolidate_references(
    refs_by_source: list[tuple[str, list[dict[str, Any]]]],
) -> list[Reference]:
    """De-duplicate references across sources and assign unique citation keys.

    ``refs_by_source`` is a list of ``(source_filename, references)`` where each
    reference is a dict with optional ``authors``/``title``/``year``/``venue``.
    Returns the pooled references (order preserved), each with a ``key`` and the
    ``source_filename`` it first appeared in.
    """
    used_keys: set[str] = set()
    seen: dict[str, Reference] = {}
    pool: list[Reference] = []
    for source_filename, refs in refs_by_source:
        for raw in refs or []:
            title = str(raw.get("title", "")).strip()
            authors = str(raw.get("authors", "")).strip()
            year = str(raw.get("year", "")).strip()
            venue = str(raw.get("venue", "")).strip()
            if not title and not authors:
                continue
            dedup = _norm(title) or _norm(authors + year)
            if not dedup or dedup in seen:
                continue
            ref: Reference = {
                "source_filename": source_filename,
                "authors": authors,
                "title": title,
                "year": year,
                "venue": venue,
            }
            # Preserve the source URL (web research) so citations can link back.
            url_val = str(raw.get("url", "")).strip()
            if url_val:
                ref["url"] = url_val
            ref["key"] = make_key(ref, used_keys)
            seen[dedup] = ref
            pool.append(ref)
    return pool


def _bib_escape(value: str) -> str:
    """Protect the few characters that would break a BibTeX field value."""
    return (value or "").replace("{", "(").replace("}", ")").replace("\\", "/").strip()


def bibtex_entry(ref: Reference) -> str:
    """Render one pooled reference as a BibTeX entry (``@article``/``@misc``)."""
    key = ref.get("key") or "ref"
    authors = _bib_escape(ref.get("authors", "")) or "Anonimo"
    title = _bib_escape(ref.get("title", "")) or "Senza titolo"
    year = re.sub(r"\D", "", ref.get("year", ""))[:4]
    venue = _bib_escape(ref.get("venue", ""))
    fields = [f"  author = {{{authors}}}", f"  title = {{{title}}}"]
    if venue:
        fields.append(f"  journal = {{{venue}}}")
    if year:
        fields.append(f"  year = {{{year}}}")
    url = ref.get("url", "").strip()
    if url:
        fields.append(f"  url = {{{url}}}")
    entry_type = "article" if venue and year else "misc"
    return f"@{entry_type}{{{key},\n" + ",\n".join(fields) + "\n}"


def cited_keys(latex: str) -> set[str]:
    """Return the set of citation keys referenced by ``\\cite``-family commands."""
    keys: set[str] = set()
    for match in _CITE_RE.finditer(latex or ""):
        for part in match.group(1).split(","):
            k = part.strip()
            if k:
                keys.add(k)
    return keys


def build_bib(pool: list[Reference], keys: set[str] | None = None) -> str:
    """Build a ``references.bib`` body. With ``keys``, keep only those entries."""
    entries = [
        bibtex_entry(r)
        for r in pool
        if r.get("key") and (keys is None or r["key"] in keys)
    ]
    return "\n\n".join(entries) + ("\n" if entries else "")


def strip_unknown_citations(latex: str, known: set[str]) -> str:
    """Drop ``\\cite`` keys that are not in ``known`` (whole command if none left)."""

    def repl(match: re.Match) -> str:
        kept = [
            k.strip()
            for k in match.group(1).split(",")
            if k.strip() and k.strip() in known
        ]
        if not kept:
            return ""
        return match.group(0).replace(match.group(1), ",".join(kept))

    return _CITE_RE.sub(repl, latex or "")


def strip_inline_bibliography(latex: str) -> str:
    """Remove any bibliography the model placed inside the body (between chapters).

    Strips ``thebibliography`` environments and stray
    ``\\bibliography``/``\\printbibliography``/``\\bibliographystyle`` commands so
    the only bibliography is the single one we add at the end of the document.
    """
    latex = _THEBIB_RE.sub("", latex or "")
    latex = _BIB_CMD_RE.sub("", latex)
    return latex
