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
    db_path: Path = BASE_DIR / "storage" / "app.db"

    # Encryption key for API keys stored in DB
    encryption_key: str = ""

    # LaTeX
    pdflatex_bin: str = "pdflatex"
    latex_compile_passes: int = 2

    # PDF extraction
    extractor_backend: str = "pymupdf"  # pymupdf | docling | markitdown
    enable_ocr: bool = False
    render_dpi: int = 130

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
