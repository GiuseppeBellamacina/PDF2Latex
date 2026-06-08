"""Composable extraction pipeline: the stage/tool registry.

The extraction step is modelled as a sequence of independent *stages*, each
responsible for one capability (digital text, document structure/tables, OCR of
scanned pages, math/equation recovery, figure extraction, figure scoring). Every
stage offers a small set of interchangeable *tools*; the user picks exactly ONE
tool per stage (no two tools doing the same job), so the pipeline is efficient
and free of redundancy.

This module is pure metadata + availability probing. It drives:

* the configuration dashboard (``GET /pipeline``) — each stage and tool carries a
  human description so the UI can explain what every choice does, plus an
  ``available`` flag and an ``install`` hint for tools that aren't installed yet;
* :class:`app.services.extractor.PipelineExtractor`, which reads a resolved
  ``pipeline_config`` (``{stage_id: tool_id}``) and orchestrates the engines.

All tools are **local and free** (run on the user's own GPU/CPU). No tool here
calls a paid API. The legacy ``hybrid`` / ``pymupdf`` / ``docling`` backends are
preserved as the default ``text``/``structure`` choices, so existing projects
keep working unchanged.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Stage / tool model                                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Tool:
    """One interchangeable engine for a stage."""

    id: str
    label: str
    description: str
    # Top-level importable module that proves the tool is installed. ``None``
    # means the tool is always available (built-in / no extra dependency).
    requires: tuple[str, ...] = ()
    # uv command hint shown in the UI when the tool isn't installed yet.
    install: str = ""
    # True for engines that benefit from (but don't require) a GPU.
    gpu: bool = False


@dataclass(frozen=True)
class Stage:
    """One capability in the pipeline; the user selects one of its tools."""

    id: str
    label: str
    description: str
    tools: tuple[Tool, ...]
    default: str  # default tool id
    optional: bool = False  # stage can be turned off entirely ("none")


# --------------------------------------------------------------------------- #
# Registry                                                                      #
# --------------------------------------------------------------------------- #

STAGES: tuple[Stage, ...] = (
    Stage(
        id="text",
        label="Testo digitale",
        description=(
            "Estrae il testo già selezionabile dal PDF, pagina per pagina. È la "
            "base veloce e affidabile per i PDF nativi (non scansionati)."
        ),
        default="pymupdf",
        tools=(
            Tool(
                id="pymupdf",
                label="PyMuPDF",
                description=(
                    "Lettura diretta del testo incorporato nel PDF. Velocissima, "
                    "nessun modello ML, ottima per documenti nativi."
                ),
                requires=("fitz",),
                install="uv sync",
            ),
        ),
    ),
    Stage(
        id="structure",
        label="Struttura & tabelle",
        description=(
            "Ricostruisce la struttura del documento (titoli, paragrafi, liste e "
            "soprattutto le TABELLE) in markdown ricco. Usato come testo "
            "principale quando disponibile."
        ),
        default="docling",
        optional=True,
        tools=(
            Tool(
                id="docling",
                label="Docling (IBM)",
                description=(
                    "Modello di layout che riconosce tabelle, intestazioni e "
                    "ordine di lettura. Eseguito in sottoprocessi isolati a "
                    "blocchi di pagine per non esaurire la memoria sui PDF grandi."
                ),
                requires=("docling",),
                install="uv sync --extra structure-docling",
                gpu=True,
            ),
            Tool(
                id="marker",
                label="Marker",
                description=(
                    "Conversione PDF→markdown ad alta fedeltà con buon supporto "
                    "per tabelle ed equazioni. Sfrutta la GPU se presente."
                ),
                requires=("marker",),
                install="uv sync --extra structure-marker",
                gpu=True,
            ),
            Tool(
                id="mineru",
                label="MinerU",
                description=(
                    "Pipeline completa di document-understanding (testo, tabelle, "
                    "formule, ordine di lettura). Ottima su paper scientifici, "
                    "richiede GPU per essere veloce."
                ),
                requires=("magic_pdf",),
                install="uv sync --extra structure-mineru",
                gpu=True,
            ),
        ),
    ),
    Stage(
        id="ocr",
        label="OCR scansioni",
        description=(
            "Legge il testo dalle pagine che sono solo immagini (scansioni, foto). "
            "Attivo solo quando una pagina ha pochissimo testo digitale."
        ),
        default="tesseract",
        optional=True,
        tools=(
            Tool(
                id="tesseract",
                label="Tesseract",
                description=(
                    "OCR classico via binario di sistema. Affidabile e leggero; "
                    "richiede l'installazione del binario Tesseract e dei language "
                    "pack."
                ),
                requires=("pytesseract",),
                install="uv sync --extra ocr-tesseract  (+ binario Tesseract)",
            ),
            Tool(
                id="rapidocr",
                label="RapidOCR",
                description=(
                    "OCR ONNX multilingue, nessun binario di sistema da "
                    "installare. Buon compromesso qualità/velocità su CPU."
                ),
                requires=("rapidocr_onnxruntime",),
                install="uv sync --extra ocr-rapidocr",
            ),
            Tool(
                id="paddleocr",
                label="PaddleOCR",
                description=(
                    "OCR molto accurato con rilevamento del layout; sfrutta la GPU "
                    "se disponibile. Ottimo su documenti complessi."
                ),
                requires=("paddleocr",),
                install="uv sync --extra ocr-paddle",
                gpu=True,
            ),
            Tool(
                id="surya",
                label="Surya",
                description=(
                    "OCR moderno basato su transformer, multilingue e robusto sui "
                    "layout difficili. Pensato per la GPU."
                ),
                requires=("surya",),
                install="uv sync --extra ocr-surya",
                gpu=True,
            ),
            Tool(
                id="dots_ocr",
                label="dots.ocr",
                description=(
                    "VLM compatto (1.7B) che fa OCR e parsing del layout in un "
                    "unico passaggio, stato dell'arte sul testo multilingue. "
                    "Richiede GPU."
                ),
                requires=("transformers",),
                install="uv sync --extra ocr-dots",
                gpu=True,
            ),
        ),
    ),
    Stage(
        id="math",
        label="Matematica & equazioni",
        description=(
            "Recupera le formule come LaTeX. Migliora nettamente i documenti "
            "scientifici con molte equazioni. Disattivabile se non servono."
        ),
        default="none",
        optional=True,
        tools=(
            Tool(
                id="pix2tex",
                label="pix2tex (LaTeX-OCR)",
                description=(
                    "Converte l'immagine di una singola equazione nel suo codice "
                    "LaTeX. Leggero, sfrutta la GPU."
                ),
                requires=("pix2tex",),
                install="uv sync --extra math-pix2tex",
                gpu=True,
            ),
            Tool(
                id="nougat",
                label="Nougat (Meta)",
                description=(
                    "Trasformer accademico che produce markdown ricco di "
                    "matematica direttamente dalle pagine. Richiede GPU."
                ),
                requires=("nougat",),
                install="uv sync --extra math-nougat",
                gpu=True,
            ),
        ),
    ),
    Stage(
        id="figures",
        label="Figure",
        description=(
            "Estrae le immagini incorporate (grafici, schemi, diagrammi) e ne "
            "cerca la didascalia reale nel testo vicino."
        ),
        default="pymupdf",
        tools=(
            Tool(
                id="pymupdf",
                label="PyMuPDF",
                description=(
                    "Estrazione diretta delle immagini raster con ricerca della "
                    "didascalia dal layout della pagina. Veloce e senza modelli."
                ),
                requires=("fitz",),
                install="uv sync",
            ),
        ),
    ),
    Stage(
        id="figure_scoring",
        label="Punteggio figure",
        description=(
            "Decide quali figure vale la pena includere nel documento finale. "
            "Combina euristiche (dimensione, proporzioni, didascalia) con un "
            "controllo opzionale del modello."
        ),
        default="heuristic",
        tools=(
            Tool(
                id="heuristic",
                label="Euristica",
                description=(
                    "Punteggio deterministico basato su dimensione, proporzioni e "
                    "presenza di una didascalia reale. Nessun costo, sempre "
                    "disponibile."
                ),
            ),
            Tool(
                id="ocr_assisted",
                label="Euristica + OCR",
                description=(
                    "Come l'euristica, ma legge anche il testo dentro la figura "
                    "(etichette di grafici/diagrammi) per rafforzare il punteggio. "
                    "Usa il motore OCR selezionato."
                ),
            ),
            Tool(
                id="vlm",
                label="Euristica + modello visione",
                description=(
                    "Aggiunge un giudizio di un modello multimodale sull'utilità "
                    "della figura. Richiede un modello con visione (come il "
                    "giudice visivo)."
                ),
                gpu=True,
            ),
        ),
    ),
)

_STAGE_BY_ID = {s.id: s for s in STAGES}


# --------------------------------------------------------------------------- #
# Availability                                                                  #
# --------------------------------------------------------------------------- #


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def tool_available(tool: Tool) -> bool:
    """A tool is available when every required module can be imported.

    Note: this checks the Python module only. Tools that also need a system
    binary (Tesseract) verify it separately at run time; the dashboard still
    surfaces them as installable so the user can pick them.
    """
    return all(_module_available(m) for m in tool.requires)


@dataclass
class _ResolvedTool:
    id: str
    label: str
    description: str
    available: bool
    install: str
    gpu: bool


@dataclass
class _ResolvedStage:
    id: str
    label: str
    description: str
    optional: bool
    default: str
    selected: str
    tools: list[_ResolvedTool] = field(default_factory=list)


def default_pipeline_config() -> dict[str, str]:
    """The default ``{stage_id: tool_id}`` mapping (legacy-equivalent)."""
    return {s.id: s.default for s in STAGES}


def normalize_pipeline_config(cfg: dict | None) -> dict[str, str]:
    """Coerce a (possibly partial/invalid) config into a valid full mapping.

    Unknown stages are dropped, unknown tools fall back to the stage default,
    and missing stages are filled with their defaults.
    """
    out = default_pipeline_config()
    if not isinstance(cfg, dict):
        return out
    for stage in STAGES:
        val = cfg.get(stage.id)
        if not isinstance(val, str):
            continue
        if stage.optional and val == "none":
            out[stage.id] = "none"
            continue
        if any(t.id == val for t in stage.tools):
            out[stage.id] = val
    return out


def describe_pipeline(cfg: dict | None = None) -> list[dict]:
    """Return the registry as plain dicts for the dashboard, with availability
    flags and the currently selected tool per stage."""
    resolved = normalize_pipeline_config(cfg)
    out: list[dict] = []
    for stage in STAGES:
        tools = [
            {
                "id": t.id,
                "label": t.label,
                "description": t.description,
                "available": tool_available(t),
                "install": t.install,
                "gpu": t.gpu,
            }
            for t in stage.tools
        ]
        out.append(
            {
                "id": stage.id,
                "label": stage.label,
                "description": stage.description,
                "optional": stage.optional,
                "default": stage.default,
                "selected": resolved[stage.id],
                "tools": tools,
            }
        )
    return out


def stage_tool(cfg: dict | None, stage_id: str) -> str:
    """The selected tool id for a stage in a (normalized) config."""
    return normalize_pipeline_config(cfg).get(
        stage_id, _STAGE_BY_ID[stage_id].default if stage_id in _STAGE_BY_ID else "none"
    )
