"""Application configuration loaded from environment / .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    app_name: str = "PDF2LaTeX"
    debug: bool = False

    host: str = "0.0.0.0"
    port: int = 8000

    # Storage paths
    data_dir: Path = BASE_DIR / "storage"
    uploads_dir: Path = BASE_DIR / "storage" / "uploads"
    output_dir: Path = BASE_DIR / "storage" / "output"
    cache_dir: Path = BASE_DIR / "storage" / "cache"
    db_path: Path = BASE_DIR / "storage" / "app.db"

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
    # Char budgets (per chunk / per section) to avoid silent truncation.
    analyzer_chunk_chars: int = 16000  # map-reduce chunk size for long docs
    analyzer_max_chunks: int = 12  # safety cap on chunks per document
    writer_source_chars: int = 14000  # relevance-selected source budget

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
