"""Async database engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Base

DATABASE_URL = f"sqlite+aiosqlite:///{settings.db_path}"

engine = create_async_engine(DATABASE_URL, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables, apply lightweight in-place migrations, and seed built-in tools."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_add_columns)
        await conn.run_sync(_seed_builtin_tools)


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
        "ocr_lang": "VARCHAR(50)",
        "judge_vision": "BOOLEAN DEFAULT 0",
        "writer_use_knowledge": "BOOLEAN DEFAULT 0",
        "user_sources": "JSON",
        "overview_latex": "TEXT",
        "bibliography_bib": "TEXT",
        "references_pool": "JSON",
        "main_tex_override": "TEXT",
        "pipeline_config": "JSON",
        "latex_template": "VARCHAR(50) DEFAULT 'default'",
        "research_mode": "BOOLEAN DEFAULT 0",
        "web_tool_id": "INTEGER",
        "web_tool_ids": "JSON",
        "research_max_queries": "INTEGER",
    },
    "figures": {
        "caption": "TEXT",
        "score": "FLOAT DEFAULT 0",
        "suggested": "BOOLEAN DEFAULT 0",
        "user_uploaded": "BOOLEAN DEFAULT 0",
        "target_section_title": "VARCHAR(512)",
        "custom_caption": "TEXT",
        "context_text": "TEXT",
    },
    "sources": {
        "source_type": "VARCHAR(50) NOT NULL DEFAULT 'pdf'",
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


def _seed_builtin_tools(sync_conn) -> None:  # noqa: ANN001
    """Create built-in web search tools that don't need API keys.

    Wikipedia and Custom HTTPX are always available when research mode is
    enabled. They are created here (idempotent — skipped if already present)
    so the user doesn't have to configure them manually.

    Also migrates existing projects from the old single-FK ``web_tool_id``
    column to the new JSON ``web_tool_ids`` column.
    """
    # Check if Wikipedia already exists.
    row = sync_conn.exec_driver_sql(
        "SELECT id FROM web_tools WHERE tool_type = 'wikipedia' LIMIT 1"
    ).first()
    if row is None:
        sync_conn.exec_driver_sql(
            "INSERT INTO web_tools (name, tool_type, is_active) "
            "VALUES ('Wikipedia (built-in)', 'wikipedia', 1)"
        )

    # Check if Web Agent already exists.
    row = sync_conn.exec_driver_sql(
        "SELECT id FROM web_tools WHERE tool_type = 'web_agent' LIMIT 1"
    ).first()
    if row is None:
        sync_conn.exec_driver_sql(
            "INSERT INTO web_tools (name, tool_type, is_active) "
            "VALUES ('Web Agent (built-in)', 'web_agent', 1)"
        )

    # Migrate existing projects: copy old web_tool_id → web_tool_ids.
    # Projects created before multi-tool support had a single FK; after this
    # change the model reads only web_tool_ids (JSON array).
    sync_conn.exec_driver_sql(
        "UPDATE projects SET web_tool_ids = json_array(web_tool_id) "
        "WHERE web_tool_ids IS NULL AND web_tool_id IS NOT NULL"
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with async_session() as session:
        yield session
