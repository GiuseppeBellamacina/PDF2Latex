"""FastAPI application entry point.

Run from the *backend* directory (one level above this file):
    cd backend
    uv run uvicorn app.main:app --reload  # development with hot-reload
    uv run python -m app.main             # shortcut (spawns uvicorn internally)
"""

from __future__ import annotations

import os
from pathlib import Path

# Suppress transitive-dependency nags that fire at import time.
# Albumentations 1.x → 2.x upgrade nag: pix2tex still uses deprecated
# parameter names removed in 2.x (e.g. `alpha_affine` in ElasticTransform).
os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.websocket import ws_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = get_logger("main")
    logger.info("Avvio %s (log level=%s)", settings.app_name, settings.log_level)
    await init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        # Only watch app/ source code.
        reload_dirs=[str(Path(__file__).resolve().parent)] if settings.debug else None,
        # Exclude patterns for uvicorn's FileFilter.
        # Mechanism A — directory names: checked via `exclude_dir in path.parents`.
        #   FileFilter calls `Path(e).is_dir()` on each entry; if True it goes to
        #   exclude_dirs and any changed .py file *inside* that tree is ignored.
        # Mechanism B — file patterns: checked via `path.match(pattern)`.
        #   FileFilter uses fnmatch‑style patterns matched from the right.
        #   Simple patterns like *.pyc work; globs like **/storage/** do NOT.
        #
        # NOTE: watchfiles.main logs *all* raw OS filesystem events (before
        # FileFilter runs), so you may still see "N changes detected" messages
        # from the `watchfiles.main` logger.  Those do NOT mean a reload is
        # happening — uvicorn only restarts when a .py file in a non-excluded
        # directory actually changed.
        reload_excludes=(
            [
                # --- directories -------------------------------------------------
                "storage",  # SQLite DB + logs + cache + output + uploads
                "storage-test",  # test database
                ".venv",  # virtual environment (10 000+ files)
                ".pytest_cache",  # pytest cache
                ".ruff_cache",  # ruff cache
                # --- file patterns (matched by fnmatch) --------------------------
                "*.pyc",  # compiled bytecode
                "*.db",  # SQLite databases
                "*.db-journal",  # SQLite rollback journal
                "*.db-wal",  # SQLite write-ahead log
                "*.db-shm",  # SQLite shared-memory index
                "*.log",  # log files
            ]
            if settings.debug
            else None
        ),
    )


if __name__ == "__main__":
    main()
