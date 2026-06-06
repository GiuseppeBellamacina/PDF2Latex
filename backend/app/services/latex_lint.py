"""Deterministic LaTeX repair pass.

Runs *before* ``pdflatex`` to fix the most common, mechanical mistakes an LLM
makes when emitting LaTeX. Catching these without an extra LLM round-trip saves
time and money and makes compilation far more reliable. The pass is
intentionally conservative: it only applies fixes that cannot change the
meaning of valid LaTeX, and it reports every change so the UI/log can show what
happened.
"""

from __future__ import annotations

import re

_FIGREF_RE = re.compile(r"\\figref\b")
# Matches both \begin{env} and \end{env} so we can walk them in document order.
_ENV_RE = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}")

# Sectioning commands whose title the model sometimes prefixes with a manual
# number ("Capitolo 2: ...") even though LaTeX numbers them on its own.
_HEADING_RE = re.compile(r"(\\(?:part|chapter|section|subsection)\*?\{)([^}]*)(\})")
_LEADING_NUMBER_RE = re.compile(
    r"^\s*(?:capitolo|chapter|parte|part|sezione|section|cap\.?|sec\.?)?\s*"
    r"\d+(?:\.\d+)*\s*[:.\)\u2013\u2014-]\s*",
    re.IGNORECASE,
)


def _strip_heading_numbering(tex: str) -> tuple[str, int]:
    """Remove a manual ``Capitolo N:`` / ``2.`` prefix from sectioning titles.

    LaTeX numbers ``\\chapter``/``\\section`` automatically, so a title like
    ``Capitolo 2: Introduzione`` renders as ``Chapter 2 Capitolo 2:
    Introduzione``. The leading manual numbering is stripped from each heading.
    """
    count = 0

    def repl(match: re.Match) -> str:
        nonlocal count
        title = match.group(2)
        cleaned = _LEADING_NUMBER_RE.sub("", title).strip()
        if cleaned and cleaned != title.strip():
            count += 1
            return match.group(1) + cleaned + match.group(3)
        return match.group(0)

    return _HEADING_RE.sub(repl, tex), count


def _strip_unresolved_figrefs(tex: str) -> tuple[str, int]:
    """Remove any leftover ``\\figref`` tokens (should already be expanded)."""
    count = len(_FIGREF_RE.findall(tex))
    if count:
        tex = _FIGREF_RE.sub("", tex)
    return tex, count


def _balance_environments(tex: str) -> tuple[str, list[str]]:
    """Append missing ``\\end{env}`` for environments left open in the body.

    Only acts on a small allow-list of body environments to avoid touching the
    document scaffold. Mismatches are returned as human-readable notes.
    """
    notes: list[str] = []
    safe_envs = {
        "equation",
        "equation*",
        "align",
        "align*",
        "gather",
        "gather*",
        "itemize",
        "enumerate",
        "figure",
        "table",
        "tabular",
        "center",
        "quote",
        "verbatim",
        "description",
        "matrix",
        "bmatrix",
        "pmatrix",
    }
    stack: list[str] = []
    for token, name in _iter_env_tokens(tex):
        if token == "begin":
            stack.append(name)
        else:  # end
            if stack and stack[-1] == name:
                stack.pop()
            elif name in stack:
                # Close inner envs implicitly until we reach the matching one.
                while stack and stack[-1] != name:
                    stack.pop()
                if stack:
                    stack.pop()
    # Anything left open on the stack is unbalanced.
    appended: list[str] = []
    for name in reversed(stack):
        if name in safe_envs:
            appended.append(f"\\end{{{name}}}")
            notes.append(f"chiuso ambiente '{name}' mancante")
    if appended:
        tex = tex.rstrip() + "\n" + "\n".join(appended) + "\n"
    return tex, notes


def _iter_env_tokens(tex: str):
    """Yield ('begin'|'end', name) in document order."""
    for m in _ENV_RE.finditer(tex):
        yield m.group(1), m.group(2)


def _balance_braces(tex: str) -> tuple[str, list[str]]:
    """Append missing closing braces when the count is slightly off.

    Ignores escaped ``\\{``/``\\}``. Only fixes small imbalances (<= 5) to
    avoid masking a deeper structural problem.
    """
    notes: list[str] = []
    opens = len(re.findall(r"(?<!\\)\{", tex))
    closes = len(re.findall(r"(?<!\\)\}", tex))
    diff = opens - closes
    if 0 < diff <= 5:
        tex = tex.rstrip() + "\n" + ("}" * diff) + "\n"
        notes.append(f"aggiunte {diff} graffe '}}' mancanti")
    elif diff < 0 and abs(diff) <= 5:
        notes.append(f"rilevate {abs(diff)} graffe '}}' in eccesso")
    return tex, notes


def _balance_inline_math(tex: str) -> tuple[str, list[str]]:
    """Detect an odd number of inline ``$`` delimiters (best-effort note)."""
    notes: list[str] = []
    # Count unescaped single $ that are not part of $$.
    stripped = tex.replace("$$", "")
    dollars = len(re.findall(r"(?<!\\)\$", stripped))
    if dollars % 2 == 1:
        notes.append("numero dispari di '$' inline (possibile formula non chiusa)")
    return tex, notes


def lint_latex(tex: str) -> tuple[str, list[str]]:
    """Apply conservative deterministic fixes. Returns ``(fixed, notes)``."""
    notes: list[str] = []

    tex, n_figref = _strip_unresolved_figrefs(tex)
    if n_figref:
        notes.append(f"rimossi {n_figref} \\figref non risolti")

    tex, n_heading = _strip_heading_numbering(tex)
    if n_heading:
        notes.append(f"rimossa numerazione manuale da {n_heading} titoli")

    tex, env_notes = _balance_environments(tex)
    notes.extend(env_notes)

    tex, brace_notes = _balance_braces(tex)
    notes.extend(brace_notes)

    _, math_notes = _balance_inline_math(tex)
    notes.extend(math_notes)

    return tex, notes
