"""Application configuration loaded from environment / .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)  # ensure storage dir exists for logs, DB


class Settings(BaseSettings):
    app_name: str = "PDF2LaTeX"
    debug: bool = False

    host: str = "0.0.0.0"
    port: int = 8000

    # Storage paths
    data_dir: Path = STORAGE_DIR
    uploads_dir: Path = STORAGE_DIR / "uploads"
    output_dir: Path = STORAGE_DIR / "output"
    cache_dir: Path = STORAGE_DIR / "cache"
    db_path: Path = STORAGE_DIR / "app.db"

    # Encryption key for API keys stored in DB
    encryption_key: str = ""

    # Logging
    log_level: str = "INFO"  # DEBUG | INFO | WARNING | ERROR
    log_to_file: bool = True

    # LaTeX
    pdflatex_bin: str = "pdflatex"
    latex_compile_passes: int = 2
    latex_lint: bool = True  # deterministic repair pass before pdflatex

    # PDF extraction
    extractor_backend: str = "hybrid"  # hybrid | pymupdf | docling
    enable_ocr: bool = False
    ocr_lang: str = "ita+eng"  # tesseract language(s); '+' to combine
    # Explicit path to the tesseract executable. Leave empty to auto-detect:
    # the app looks on PATH and in the standard Windows install locations
    # (e.g. C:\Program Files\Tesseract-OCR\tesseract.exe).
    tesseract_cmd: str = ""
    render_dpi: int = 130
    # Docling renders every page through ML layout models; on large PDFs this
    # exhausts memory (std::bad_alloc). The hybrid backend therefore runs
    # Docling in isolated subprocesses, one page-range chunk at a time, so the
    # OS reclaims memory between chunks. Above ``docling_max_pages`` Docling is
    # skipped entirely and PyMuPDF text is used.
    docling_max_pages: int = 200
    docling_chunk_pages: int = 8  # pages per isolated Docling subprocess
    docling_enable_tables: bool = True  # recover tables as structured markdown
    docling_subprocess_timeout: int = 600  # seconds per chunk before giving up
    extraction_cache: bool = True  # cache Docling markdown by file hash
    dedup_headers_footers: bool = True  # strip recurring page headers/footers

    # LLM orchestration
    llm_max_concurrency: int = 4  # max simultaneous LLM calls (fan-out cap)
    llm_max_retries: int = 4  # retries on transient errors (429/5xx/timeouts)
    llm_retry_base_delay: float = 1.5  # seconds; exponential backoff base
    llm_request_timeout: int = 180  # seconds per LLM call
    # Per-role sampling temperatures (extraction tasks want determinism).
    analyzer_temperature: float = 0.0
    planner_temperature: float = 0.1
    writer_temperature: float = 0.3
    reviewer_temperature: float = 0.0
    judge_temperature: float = 0.0
    # Char budgets (per chunk / per section) to avoid silent truncation.
    analyzer_chunk_chars: int = 16000  # map-reduce chunk size for long docs
    analyzer_max_chunks: int = 12  # safety cap on chunks per document
    writer_source_chars: int = 14000  # relevance-selected source budget

    # Judge: after a successful compile, an LLM "judge" inspects the overall
    # document structure (intro/conclusion, chapter order, balance, duplicates,
    # figure placement) and, if needed, requests a structural revision that is
    # re-linted and re-compiled. Bounded iterations keep cost/time in check.
    judge_enabled: bool = True
    judge_max_iterations: int = 1  # structural revision rounds after first PDF
    # Deterministic layout inspection (no LLM, no multimodal): measures the
    # compiled PDF (oversized/clustered figures, near-empty pages) and parses
    # the pdflatex log (overfull/underfull boxes) to give the text judge concrete
    # facts about layout/figure problems. This is the default critique source.
    judge_layout_inspect: bool = True
    # Vision judge (OPTIONAL, OFF by default): render the compiled PDF pages and
    # let a *vision-capable* model review them. Requires a multimodal model
    # (e.g. gpt-4o, claude-3.5). Leave disabled if you don't have one — the
    # layout inspector above already feeds figure/layout issues to the judge.
    judge_vision: bool = False
    judge_vision_max_pages: int = 12  # cap pages sent to the vision model
    judge_vision_dpi: int = 110  # render DPI for the judged page images

    # Figures
    # Each mandatory figure is placed in exactly ONE section (distributed across
    # the sections that use its source), and no image is ever inserted twice in
    # the whole document. These caps keep slide decks from flooding a section.
    max_figures_per_section: int = 4  # hard cap of figures rendered per section
    figure_width_ratio: float = 0.62  # \includegraphics width as fraction of line
    figure_max_height_ratio: float = 0.42  # cap height as fraction of \textheight

    # Defaults
    default_language: str = "italian"

    # CORS
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PDF2TEX_",
        extra="ignore",
    )


settings = Settings()

# Ensure storage directories exist
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.cache_dir.mkdir(parents=True, exist_ok=True)
