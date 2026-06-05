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

    tex, env_notes = _balance_environments(tex)
    notes.extend(env_notes)

    tex, brace_notes = _balance_braces(tex)
    notes.extend(brace_notes)

    _, math_notes = _balance_inline_math(tex)
    notes.extend(math_notes)

    return tex, notes
