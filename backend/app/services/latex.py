"""LaTeX document assembly and compilation."""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

PREAMBLE = r"""\documentclass[11pt,a4paper]{report}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[%(language)s]{babel}
\usepackage{amsmath,amssymb,amsthm}
\usepackage{graphicx}
\usepackage{float}
\usepackage{enumitem}
\usepackage{booktabs}
\usepackage{array}
\usepackage{tabularx}
\usepackage{adjustbox}
\usepackage[hidelinks]{hyperref}
\usepackage{geometry}
\geometry{margin=2.5cm}

\newcommand{\inbreve}[1]{\breve{#1}}

\begin{document}
"""

TITLE_PAGE = r"""\begin{titlepage}
\centering
\vspace*{3cm}
{\Huge\bfseries %(title)s\par}
%(subtitle_block)s
\vspace{1.5cm}
{\Large %(author)s\par}
\vspace{0.5cm}
{\large %(date)s\par}
\vfill
\end{titlepage}
"""

ABSTRACT_BLOCK = r"""\begin{abstract}
%(abstract)s
\end{abstract}
"""

FRONT_MATTER_TAIL = r"""\tableofcontents
\clearpage
"""

# Appended (when the document cites references) right before \end{document} so
# the single, structured bibliography always sits at the very end.
BIBLIOGRAPHY_BLOCK = r"""\clearpage
\bibliographystyle{plain}
\bibliography{references}
"""

POSTAMBLE = r"""
\end{document}
"""


@dataclass
class CompileResult:
    success: bool
    pdf_path: str | None
    log: str


# Map our language values to the option name expected by the babel package.
# Anything unknown falls through to ``english`` so compilation never breaks.
_BABEL_LANGUAGES: dict[str, str] = {
    "english": "english",
    "italian": "italian",
    "french": "french",
    "german": "ngerman",
    "spanish": "spanish",
    "portuguese": "portuguese",
    "dutch": "dutch",
    "russian": "russian",
    "polish": "polish",
    "swedish": "swedish",
}


def _babel_language(language: str) -> str:
    """Resolve a language value to a valid babel option name."""
    key = (language or "").strip().lower()
    if key.startswith("ital"):
        return "italian"
    return _BABEL_LANGUAGES.get(key, "english")


def assemble_document(
    title: str,
    body_parts: list[str],
    language: str = "italian",
    author: str = "PDF2LaTeX",
    subtitle: str = "",
    abstract: str = "",
    cover_date: str = "",
    has_bibliography: bool = False,
) -> str:
    """Join the preamble, title page, optional abstract, body and postamble.

    When ``has_bibliography`` is set, a single ``\\bibliography{references}`` block
    is appended at the very end of the document (after all chapters).
    """
    babel_lang = _babel_language(language)
    preamble = PREAMBLE % {"language": babel_lang}

    subtitle_block = ""
    if subtitle:
        subtitle_block = (
            "\\vspace{0.6cm}\n{\\Large\\itshape " + _escape(subtitle) + "\\par}"
        )
    title_page = TITLE_PAGE % {
        "title": _escape(title),
        "subtitle_block": subtitle_block,
        "author": _escape(author),
        "date": _escape(cover_date) if cover_date else r"\today",
    }

    abstract_block = ""
    if abstract:
        abstract_block = ABSTRACT_BLOCK % {"abstract": _escape(abstract)}

    body = "\n\n".join(body_parts)
    bibliography = ("\n" + BIBLIOGRAPHY_BLOCK) if has_bibliography else ""
    return (
        preamble
        + title_page
        + abstract_block
        + FRONT_MATTER_TAIL
        + "\n"
        + body
        + "\n"
        + bibliography
        + POSTAMBLE
    )


def slugify_title(title: str, fallback: str = "documento") -> str:
    """Turn a document title into a safe filename stem (no extension)."""
    slug = re.sub(r"[^\w\s-]", "", (title or "").strip().lower(), flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:80] or fallback


def inject_bibliography(latex: str) -> str:
    """Insert the single end-of-document bibliography block before \\end{document}.

    Assumes any pre-existing bibliography commands were already stripped. No-op
    when the block is already present.
    """
    if "\\bibliography{references}" in latex:
        return latex
    if "\\end{document}" not in latex:
        return latex.rstrip() + "\n\n" + BIBLIOGRAPHY_BLOCK
    return latex.replace("\\end{document}", BIBLIOGRAPHY_BLOCK + "\\end{document}", 1)


def _split_header_and_body(full_latex: str) -> tuple[str, str, str]:
    """Split a full document into (header, body, footer).

    header = everything up to and including ``\\begin{document}`` plus the
    front-matter (title page / abstract / table of contents); body = the actual
    chapters/sections; footer = ``\\end{document}``. Falls back gracefully if
    the markers are missing.
    """
    begin = full_latex.find(r"\begin{document}")
    end = full_latex.rfind(r"\end{document}")
    if begin == -1 or end == -1:
        return full_latex, "", ""
    begin += len(r"\begin{document}")
    inner = full_latex[begin:end]
    footer = r"\end{document}"
    # Keep front matter (title/abstract/toc) in the header so parts contain only
    # real content. The first \chapter (or \section) marks the body start.
    m = re.search(r"\\chapter\{|\\section\{", inner)
    if not m:
        return full_latex[:begin], inner, footer
    header = full_latex[:begin] + inner[: m.start()]
    body = inner[m.start() :]
    return header, body, footer


def split_into_part_files(full_latex: str) -> tuple[str, dict[str, str]]:
    """Build a modular project from a monolithic document.

    Returns ``(main_tex, parts)`` where ``main_tex`` keeps the preamble, title
    page and table of contents and then ``\\input{parts/<name>}`` for each
    chapter, and ``parts`` maps ``parts/<name>.tex`` -> chapter content. If the
    document has no chapters, a single ``parts/part-01.tex`` is produced. The
    assembled ``main_tex`` is equivalent to the input and still compiles.
    """
    header, body, footer = _split_header_and_body(full_latex)
    if not body.strip():
        # Nothing to split: keep a single part so the zip stays modular.
        parts = {"parts/part-01.tex": full_latex}
        return full_latex, parts

    # Split on top-level \chapter{...} boundaries, keeping the command.
    chunks = re.split(r"(?=\\chapter\{)", body)
    chunks = [c for c in chunks if c.strip()]
    if not chunks:
        chunks = [body]

    parts: dict[str, str] = {}
    inputs: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        title_match = re.search(r"\\chapter\{([^}]*)\}", chunk)
        stem = slugify_title(title_match.group(1) if title_match else f"part-{i:02d}")
        name = f"part-{i:02d}-{stem}"[:60]
        rel = f"parts/{name}.tex"
        parts[rel] = chunk.strip() + "\n"
        inputs.append(f"\\input{{parts/{name}}}")

    # Keep the bibliography commands in main.tex (not buried in the last part),
    # so the modular project mirrors the monolithic one and compiles with bibtex.
    bib_re = re.compile(
        r"\n?\\bibliographystyle\{[^}]*\}\s*\\bibliography\{[^}]*\}\s*", re.DOTALL
    )
    bib_block = ""
    for rel, content in list(parts.items()):
        m = bib_re.search(content)
        if m:
            bib_block = "\\bibliographystyle{plain}\n\\bibliography{references}\n"
            parts[rel] = bib_re.sub("\n", content).rstrip() + "\n"

    tail = ("\n\\clearpage\n" + bib_block) if bib_block else ""
    main_tex = (
        header.rstrip() + "\n\n" + "\n".join(inputs) + tail + "\n\n" + footer + "\n"
    )
    return main_tex, parts


def build_project_zip(
    zip_path: Path,
    main_tex: str,
    parts: dict[str, str],
    figures_dir: Path | None = None,
    bib_content: str | None = None,
) -> Path:
    """Write a self-contained LaTeX project zip: main.tex + parts/ + figures/.

    When ``bib_content`` is provided, a ``references.bib`` is included so the
    project compiles with bibtex out of the box.
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("main.tex", main_tex)
        for rel, content in parts.items():
            zf.writestr(rel, content)
        if bib_content and bib_content.strip():
            zf.writestr("references.bib", bib_content)
        if figures_dir and figures_dir.exists():
            for fig in sorted(figures_dir.iterdir()):
                if fig.is_file():
                    zf.write(fig, f"figures/{fig.name}")
    return zip_path


_INCLUDE_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_FIGURE_ENV_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.DOTALL)
_TABULAR_RE = re.compile(
    r"\\begin\{(tabular|tabularx|array)\}.*?\\end\{\1\}", re.DOTALL
)


def fit_wide_tables(tex: str) -> str:
    """Shrink-to-fit any ``tabular`` that could run off the page edge.

    Each ``tabular``/``array`` block is wrapped in an ``adjustbox`` with
    ``max width=\\linewidth`` so a wide table is scaled down to the text width
    instead of overflowing into the margin; tables that already fit are left at
    their natural size (``adjustbox`` only shrinks, never enlarges). Blocks
    already wrapped in ``adjustbox``/``resizebox`` are skipped.
    """

    def wrap(match: re.Match) -> str:
        block = match.group(0)
        # Don't double-wrap if the author/model already handled sizing.
        preceding = tex[max(0, match.start() - 60) : match.start()]
        if "adjustbox" in preceding or "resizebox" in preceding:
            return block
        return (
            "\\begin{adjustbox}{max width=\\linewidth}\n" + block + "\n\\end{adjustbox}"
        )

    return _TABULAR_RE.sub(wrap, tex)


def _available_figures(figures_dir: Path) -> dict[str, str]:
    """Map every available figure (by basename, case-folded) to ``figures/<name>``."""
    out: dict[str, str] = {}
    if figures_dir.exists():
        for p in figures_dir.iterdir():
            if p.is_file():
                out[p.name.lower()] = f"figures/{p.name}"
    return out


def sanitize_figures(tex: str, figures_dir: Path) -> tuple[str, list[str]]:
    """Fix or remove figure references that do not resolve to a real file.

    For each ``\\includegraphics`` the basename is looked up among the files
    actually present in ``figures_dir``. If found, the path is normalised to
    ``figures/<name>`` (fixing wrong folders/paths). If not found, the
    enclosing ``figure`` environment (or the bare command) is removed so a
    missing image cannot abort the whole compilation. Returns the cleaned
    LaTeX and the list of dropped basenames.
    """
    available = _available_figures(figures_dir)
    dropped: list[str] = []

    def resolve(path: str) -> str | None:
        return available.get(Path(path.strip()).name.lower())

    def handle_env(match: re.Match) -> str:
        block = match.group(0)
        includes = _INCLUDE_RE.findall(block)
        if not includes:
            return block
        new_block = block
        for inc in includes:
            fixed = resolve(inc)
            if fixed is None:
                dropped.append(Path(inc).name)
                return ""  # drop the entire figure environment
            if fixed != inc:
                new_block = new_block.replace("{" + inc + "}", "{" + fixed + "}")
        return new_block

    tex = _FIGURE_ENV_RE.sub(handle_env, tex)

    # Stray \includegraphics not wrapped in a figure environment.
    def handle_inc(match: re.Match) -> str:
        inc = match.group(1)
        fixed = resolve(inc)
        if fixed is None:
            dropped.append(Path(inc).name)
            return ""
        if fixed != inc:
            return match.group(0).replace("{" + inc + "}", "{" + fixed + "}")
        return match.group(0)

    tex = _INCLUDE_RE.sub(handle_inc, tex)
    return tex, dropped


def write_and_compile(
    tex_content: str,
    work_dir: Path,
    figures_src: Path | None = None,
    job_name: str = "main",
    allowed_figures: set[str] | None = None,
    bib_content: str | None = None,
) -> CompileResult:
    """Write ``tex_content`` into ``work_dir`` and compile it with pdflatex.

    ``allowed_figures`` (basenames) restricts which images are copied into the
    project: only those are placed in ``work_dir/figures``, so unselected
    figures can never appear in the PDF nor in the downloadable zip. The figures
    folder is rebuilt each run to drop anything left by a previous run.
    ``bib_content``, when set and the document uses ``\\bibliography``, is written
    as ``references.bib`` and a ``bibtex`` pass is run so citations resolve.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    tex_path = work_dir / f"{job_name}.tex"

    dest = work_dir / "figures"
    if figures_src and figures_src.exists() and dest.resolve() != figures_src.resolve():
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        allowed_lower = (
            {a.lower() for a in allowed_figures}
            if allowed_figures is not None
            else None
        )
        for p in figures_src.iterdir():
            if not p.is_file():
                continue
            if allowed_lower is None or p.name.lower() in allowed_lower:
                shutil.copy2(p, dest / p.name)

    # Drop/fix references to figures that do not exist so a single hallucinated
    # \includegraphics cannot abort the whole compilation.
    tex_content, dropped = sanitize_figures(tex_content, work_dir / "figures")
    # Scale oversized tables down to the text width so they don't run off-page.
    tex_content = fit_wide_tables(tex_content)
    tex_path.write_text(tex_content, encoding="utf-8")

    # Write the bibliography database and decide whether a bibtex pass is needed.
    use_bibtex = bool(
        bib_content and bib_content.strip() and r"\bibliography{" in tex_content
    )
    if bib_content and bib_content.strip():
        (work_dir / "references.bib").write_text(bib_content, encoding="utf-8")

    log_acc: list[str] = []
    if dropped:
        log_acc.append(
            f"[sanitize] Rimosse {len(dropped)} figure inesistenti: "
            + ", ".join(sorted(set(dropped))[:20])
        )
    pdf_path = work_dir / f"{job_name}.pdf"

    def _pdflatex() -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                settings.pdflatex_bin,
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-jobname={job_name}",
                tex_path.name,
            ],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )

    # With bibtex we need: pdflatex -> bibtex -> pdflatex -> pdflatex so labels
    # and the bibliography resolve. Without it, the plain N-pass loop is used.
    passes = max(1, settings.latex_compile_passes)
    if use_bibtex:
        first = _pdflatex()
        log_acc.append(first.stdout[-4000:])
        if first.returncode != 0:
            return CompileResult(success=False, pdf_path=None, log="\n".join(log_acc))
        try:
            bib = subprocess.run(
                [settings.bibtex_bin, job_name],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            log_acc.append("[bibtex]\n" + (bib.stdout or "")[-2000:])
        except (OSError, subprocess.SubprocessError) as exc:
            # bibtex missing/failed: keep going so the document still compiles
            # (citations will show as [?] but the build does not abort).
            log_acc.append(f"[bibtex] non eseguito: {exc}")
        passes = max(2, passes)

    for _ in range(passes):
        proc = _pdflatex()
        log_acc.append(proc.stdout[-4000:])
        if proc.returncode != 0:
            return CompileResult(success=False, pdf_path=None, log="\n".join(log_acc))

    success = pdf_path.exists()
    return CompileResult(
        success=success,
        pdf_path=str(pdf_path) if success else None,
        log="\n".join(log_acc),
    )


def _escape(text: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text
