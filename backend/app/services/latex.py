"""LaTeX document assembly and compilation."""

from __future__ import annotations

import shutil
import subprocess
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

\title{%(title)s}
\author{%(author)s}
\date{\today}

\begin{document}
\maketitle
\tableofcontents
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


def assemble_document(
    title: str,
    body_parts: list[str],
    language: str = "italian",
    author: str = "PDF2LaTeX",
) -> str:
    """Join the preamble, generated body parts and postamble into one .tex string."""
    babel_lang = "italian" if language.lower().startswith("ital") else language.lower()
    preamble = PREAMBLE % {
        "language": babel_lang,
        "title": _escape(title),
        "author": _escape(author),
    }
    body = "\n\n".join(body_parts)
    return preamble + "\n" + body + "\n" + POSTAMBLE


def write_and_compile(
    tex_content: str,
    work_dir: Path,
    figures_src: Path | None = None,
    job_name: str = "main",
) -> CompileResult:
    """Write ``tex_content`` into ``work_dir`` and compile it with pdflatex."""
    work_dir.mkdir(parents=True, exist_ok=True)
    tex_path = work_dir / f"{job_name}.tex"
    tex_path.write_text(tex_content, encoding="utf-8")

    if figures_src and figures_src.exists():
        dest = work_dir / "figures"
        if dest.resolve() != figures_src.resolve():
            shutil.copytree(figures_src, dest, dirs_exist_ok=True)

    log_acc: list[str] = []
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
