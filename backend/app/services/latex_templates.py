"""LaTeX template registry.

Each template is a Python format string with these placeholders:
  %(language)s     — babel language option
  %(title)s        — escaped title
  %(subtitle)s     — escaped subtitle (may be empty)
  %(author)s       — escaped author
  %(date)s         — escaped date (or \\today)
  %(abstract)s     — abstract block (may be empty)
  %(toc)s          — table of contents block (may be empty)
  %(body)s         — dynamically generated chapters
  %(bibliography)s — bibliography block (may be empty)

The ``default`` template is built-in (always available). Additional
templates may be loaded from the ``ref/`` directory in the project root.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Built-in default template (current report class) ──────────────────────
_DEFAULT_TEMPLATE = r"""\documentclass[11pt,a4paper]{report}
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
\begin{titlepage}
\centering
\vspace*{3cm}
{\Huge\bfseries %(title)s\par}
%(subtitle)s
\vspace{1.5cm}
{\Large %(author)s\par}
\vspace{0.5cm}
{\large %(date)s\par}
\vfill
\end{titlepage}
%(abstract)s
%(toc)s
%(body)s
%(bibliography)s
\end{document}
"""

# ── IEEEtran scientific paper (from ref/paper.tex) ────────────────────────
_IEEE_PAPER_TEMPLATE = r"""\documentclass[conference]{IEEEtran}

% ---- Packages ----
\usepackage{cite}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage[%(language)s]{babel}
\usepackage{graphicx}
\usepackage[font=small,labelfont=bf]{caption}
\usepackage{subcaption}
\usepackage{booktabs}
\usepackage{array}
\usepackage{multirow}
\usepackage{float}
\usepackage{hyperref}
\usepackage{xcolor}
\usepackage{textcomp}
\usepackage{balance}
\usepackage{microtype}

% ---- Code listings ----
\usepackage{listings}
\usepackage{inconsolata}

\definecolor{commentsgreen}{rgb}{0, 0.6, 0}
\definecolor{codegray}{rgb}{0.5, 0.5, 0.5}
\definecolor{keywordpurple}{rgb}{0.58, 0.0, 0.83}
\definecolor{backcolour}{rgb}{0.95, 0.95, 0.95}
\definecolor{stringbrown}{rgb}{0.8, 0.51, 0.298}

\lstset{
    language=Python,
    basicstyle=\scriptsize\ttfamily,
    numbers=left,
    numberstyle=\tiny\ttfamily\color{codegray},
    numbersep=6pt,
    tabsize=4,
    breaklines=true,
    backgroundcolor=\color{backcolour},
    commentstyle=\color{commentsgreen},
    keywordstyle=\color{keywordpurple},
    stringstyle=\color{stringbrown},
    showspaces=false,
    showtabs=false,
    showstringspaces=false,
    captionpos=b,
    frame=single,
    framesep=3pt
}

% ---- Figures always at top ----
\makeatletter
\setlength{\@fptop}{0pt}
\makeatother

% ---- Custom commands ----
\newcommand{\ie}{\textit{i.e.}}
\newcommand{\eg}{\textit{e.g.}}
\newcommand{\etal}{\textit{et al.}}

% ---- Fix uneven word spacing in narrow columns ----
\tolerance=1000
\emergencystretch=1.5em
\hbadness=10000

\begin{document}
%(paper_title)s
%(body)s
%(bibliography)s
\end{document}
"""

# ── Thesis (Solo Fronte) — from ref/Tesi_SoloFronte.tex ──────────────────
_THESIS_ONESIDE_TEMPLATE = r"""\documentclass[12pt,a4paper,openany,oneside]{book}

\usepackage{hyperref}
\usepackage[%(language)s]{babel}

\usepackage[utf8x]{inputenc}
\usepackage[T1]{fontenc}

\usepackage{graphicx}
\usepackage[font=small,labelfont=bf,tableposition=top]{caption}

\usepackage[headheight=12pt, textheight=592pt, marginparsep=7pt, footskip=30pt, hoffset=0pt, paperwidth=597pt,
            top=127pt, headsep=19pt, textwidth=390pt, marginparwidth=38pt, voffset=0pt, paperheight=845pt,
            left=117pt, right=90pt]{geometry}
\usepackage{listings}
\usepackage{inconsolata}
\usepackage{xcolor}
\usepackage[framemethod=tikz]{mdframed}

\definecolor{commentsgreen}{rgb}{0, 0.6, 0}
\definecolor{codegray}{rgb}{0.5, 0.5, 0.5}
\definecolor{keywordpurple}{rgb}{0.77, 0.525, 0.75}
\definecolor{backcolour}{rgb}{0.12, 0.12, 0.12}
\definecolor{functionyellow}{rgb}{0.86, 0.86, 0.667}
\definecolor{basicblue}{rgb}{0.61, 0.86, 1}
\definecolor{classgreen}{rgb}{0.294, 0.745, 0.6}
\definecolor{numberyellow}{rgb}{0.686, 0.705, 0.435}
\definecolor{stringbrown}{rgb}{0.8, 0.51, 0.298}
\definecolor{defblue}{rgb}{0.2, 0.32, 0.833}
\definecolor{constantblue}{rgb}{0.2, 0.705, 1}

\lstset{
        language=Python,
        basicstyle=\footnotesize\ttfamily\color{basicblue},
        numbers=left,
        numberstyle=\tiny\ttfamily\color{codegray},
        numbersep=8pt,
        tabsize=5,
        escapeinside={(*@}{@*)},
        extendedchars=true,
        breaklines=true,
        backgroundcolor=\color{backcolour},
        commentstyle=\ttfamily\color{commentsgreen},
        keywordstyle=\ttfamily\color{keywordpurple},
        deletekeywords={print, dict, all, list, str},
        stringstyle=\ttfamily\color{stringbrown},
        showspaces=false,
        showtabs=false,
        xleftmargin=17pt,
        framexleftmargin=17pt,
        framexrightmargin=5pt,
        framexbottommargin=4pt,
        showstringspaces=false,
        captionpos=b,
}

\addto\captions%(language)s{
        \renewcommand{\lstlistingname}{Codice}}

\setcounter{tocdepth}{2}
\setcounter{secnumdepth}{2}

\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{float}
\usepackage{framed}
\usepackage{layout}

\begin{document}

\newgeometry{top=2.5cm, bottom=3cm, left=2.5cm, right=2.5cm}
%(title)s
\restoregeometry

%(abstract)s

%(toc)s

%(body)s

\newpage

% Bibliografia
\addcontentsline{toc}{chapter}{Bibliografia}
%(bibliography)s

\end{document}
"""

# ── Thesis (Fronte Retro) — from ref/Tesi_FronteRetro.tex ────────────────
_THESIS_TWOSIDE_TEMPLATE = (
    _THESIS_ONESIDE_TEMPLATE.replace(
        r"\documentclass[12pt,a4paper,openany,oneside]{book}",
        r"\documentclass[12pt,a4paper,openright,twoside]{book}",
    )
    .replace(
        r"left=117pt, right=90pt]{geometry}",
        r"inner=117pt, outer=90pt]{geometry}",
    )
    .replace(
        "\\begin{document}",
        "\\begin{document}\n\\raggedbottom",
    )
)


@dataclass(frozen=True)
class Template:
    """Metadata + format string for one LaTeX document template."""

    id: str
    label: str
    description: str
    _fmt: str  # Python format string with %(...)s placeholders

    def render(self, **kwargs: str) -> str:
        """Fill in placeholders and return the complete document."""
        return self._fmt % {k: v for k, v in kwargs.items() if k != "self"}


# ── Registry ───────────────────────────────────────────────────────────────
_TEMPLATES: dict[str, Template] = {
    "default": Template(
        id="default",
        label="Riassunto (Report)",
        description="Documento standard con frontespizio, abstract, indice. Classe report.",
        _fmt=_DEFAULT_TEMPLATE,
    ),
    "paper": Template(
        id="paper",
        label="Paper Scientifico (IEEEtran)",
        description="Articolo scientifico a due colonne in stile IEEE. Nessun indice.",
        _fmt=_IEEE_PAPER_TEMPLATE,
    ),
    "thesis-oneside": Template(
        id="thesis-oneside",
        label="Tesi di Laurea (Solo Fronte)",
        description="Tesi in classe book con margine sinistro maggiorato per rilegatura. Capitoli aperti ovunque.",
        _fmt=_THESIS_ONESIDE_TEMPLATE,
    ),
    "thesis-twoside": Template(
        id="thesis-twoside",
        label="Tesi di Laurea (Fronte/Retro)",
        description="Tesi in classe book con margini inner/outer per stampa fronte-retro. Capitoli aperti a destra.",
        _fmt=_THESIS_TWOSIDE_TEMPLATE,
    ),
}


def get_template(template_id: str) -> Template:
    """Return the template with the given id (falls back to ``default``)."""
    return _TEMPLATES.get(template_id, _TEMPLATES["default"])


def list_templates() -> list[dict]:
    """Return metadata for all available templates (for the API/UI)."""
    return [
        {"id": t.id, "label": t.label, "description": t.description}
        for t in _TEMPLATES.values()
    ]
