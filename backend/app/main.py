"""FastAPI application entry point.

Run from the *backend* directory (one level above this file):
    cd backend
    uv run uvicorn app.main:app --reload  # development with hot-reload
    uv run python -m app.main             # shortcut (spawns uvicorn internally)
"""

from __future__ import annotations

import os

# Suppress transitive-dependency nags that fire at import time.
# Albumentations 1.x → 2.x upgrade nag: we pin <2.0 because nougat-ocr still
# passes the deprecated `alpha_affine` kwarg (removed in 2.x).
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
        # Only watch our source; otherwise the reloader scans .venv and
        # restarts the server mid-request when packages touch files.
        reload_dirs=["app"] if settings.debug else None,
    )


if __name__ == "__main__":
    main()
