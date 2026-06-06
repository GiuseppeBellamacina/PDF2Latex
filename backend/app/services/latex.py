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
) -> str:
    """Join the preamble, title page, optional abstract, body and postamble."""
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
    return (
        preamble
        + title_page
        + abstract_block
        + FRONT_MATTER_TAIL
        + "\n"
        + body
        + "\n"
        + POSTAMBLE
    )


def slugify_title(title: str, fallback: str = "documento") -> str:
    """Turn a document title into a safe filename stem (no extension)."""
    slug = re.sub(r"[^\w\s-]", "", (title or "").strip().lower(), flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:80] or fallback


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

    main_tex = header.rstrip() + "\n\n" + "\n".join(inputs) + "\n\n" + footer + "\n"
    return main_tex, parts


def build_project_zip(
    zip_path: Path,
    main_tex: str,
    parts: dict[str, str],
    figures_dir: Path | None = None,
) -> Path:
    """Write a self-contained LaTeX project zip: main.tex + parts/ + figures/."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("main.tex", main_tex)
        for rel, content in parts.items():
            zf.writestr(rel, content)
        if figures_dir and figures_dir.exists():
            for fig in sorted(figures_dir.iterdir()):
                if fig.is_file():
                    zf.write(fig, f"figures/{fig.name}")
    return zip_path


_INCLUDE_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_FIGURE_ENV_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.DOTALL)


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
) -> CompileResult:
    """Write ``tex_content`` into ``work_dir`` and compile it with pdflatex."""
    work_dir.mkdir(parents=True, exist_ok=True)
    tex_path = work_dir / f"{job_name}.tex"

    if figures_src and figures_src.exists():
        dest = work_dir / "figures"
        if dest.resolve() != figures_src.resolve():
            shutil.copytree(figures_src, dest, dirs_exist_ok=True)

    # Drop/fix references to figures that do not exist so a single hallucinated
    # \includegraphics cannot abort the whole compilation.
    tex_content, dropped = sanitize_figures(tex_content, work_dir / "figures")
    tex_path.write_text(tex_content, encoding="utf-8")

    log_acc: list[str] = []
    if dropped:
        log_acc.append(
            f"[sanitize] Rimosse {len(dropped)} figure inesistenti: "
            + ", ".join(sorted(set(dropped))[:20])
        )
    pdf_path = work_dir / f"{job_name}.pdf"
    passes = max(1, settings.latex_compile_passes)
    for _ in range(passes):
        proc = subprocess.run(
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
