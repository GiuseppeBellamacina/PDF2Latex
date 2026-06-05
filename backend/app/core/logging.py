"""Centralised logging configuration for the backend.

Provides a single :func:`setup_logging` entry point (called once at startup)
and a :func:`get_logger` helper used across services and agents. Logs go to the
console and, optionally, to a rotating file under ``storage/``. The format is
compact but includes the logger name so it is easy to follow a request as it
travels extract -> analyze -> plan -> write -> review.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import settings

_CONFIGURED = False

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
_DATEFMT = "%H:%M:%S"


def setup_logging() -> None:
    """Configure the root logger. Idempotent: safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers if uvicorn already configured the root logger.
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)

    if settings.log_to_file:
        try:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                settings.data_dir / "pdf2latex.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            root.addHandler(file_handler)
        except OSError:  # pragma: no cover - file logging is best-effort
            pass

    # Tame noisy third-party loggers.
    for noisy in ("httpx", "httpcore", "urllib3", "PIL", "docling"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, ensuring logging is configured first."""
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)
