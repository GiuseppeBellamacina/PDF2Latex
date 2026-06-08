"""Async database engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Base

DATABASE_URL = f"sqlite+aiosqlite:///{settings.db_path}"

engine = create_async_engine(DATABASE_URL, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables and apply lightweight in-place migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_add_columns)


# New columns added after the first schema version. SQLite can ADD COLUMN
# cheaply, so for this single-user local app we patch existing tables in place.
_MIGRATIONS: dict[str, dict[str, str]] = {
    "projects": {
        "public_id": "VARCHAR(32) UNIQUE NOT NULL DEFAULT (lower(hex(randomblob(16))))",
        "author": "VARCHAR(255)",
        "subtitle": "VARCHAR(512)",
        "abstract": "TEXT",
        "cover_date": "VARCHAR(100)",
        "structure_hint": "TEXT",
        "extractor_backend": "VARCHAR(50)",
        "enable_ocr": "BOOLEAN DEFAULT 0",
        "judge_vision": "BOOLEAN DEFAULT 0",
        "overview_latex": "TEXT",
        "bibliography_bib": "TEXT",
        "references_pool": "JSON",
        "main_tex_override": "TEXT",
        "pipeline_config": "JSON",
    },
    "figures": {
        "caption": "TEXT",
        "score": "FLOAT DEFAULT 0",
        "suggested": "BOOLEAN DEFAULT 0",
    },
    "sections": {
        "source_filenames": "JSON",
        "previous_latex": "TEXT",
    },
}


def _migrate_add_columns(sync_conn) -> None:  # noqa: ANN001 - sqlalchemy Connection
    for table, columns in _MIGRATIONS.items():
        existing = {
            row[1] for row in sync_conn.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        for col, ddl in columns.items():
            if col not in existing:
                sync_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with async_session() as session:
        yield session
