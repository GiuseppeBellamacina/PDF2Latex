# PDF2LaTeX — Agent Guide

## Repository structure

```
PDF2Latex/
├── backend/          # FastAPI + LangGraph (Python 3.11-3.13, uv)
│   ├── app/
│   │   ├── main.py          # Entry: uvicorn app.main:app
│   │   ├── agents/          # LangGraph pipeline nodes (graph.py is the core)
│   │   ├── api/             # REST + WebSocket routes
│   │   ├── core/            # Config, LLM factory, encryption, logging
│   │   ├── db/              # SQLite (SQLAlchemy + aiosqlite)
│   │   └── services/        # Extractors, OCR, math engines, web search, LaTeX compilation
│   ├── tests/               # pytest, asyncio_mode=auto
│   ├── pyproject.toml       # Ruff, pytest, uv index for pytorch CUDA
│   ├── .env.example         # All PDF2TEX_* vars documented
│   └── .env.test            # Loaded automatically by conftest.py
├── frontend/         # React + Vite + Tailwind (Bun)
│   ├── src/
│   │   ├── main.tsx         # Entry
│   │   ├── App.tsx          # Routes: /, /configure/:id, /generate/:id, /preview/:id, /history, /settings
│   │   └── pages/           # One component per route
│   └── package.json
├── tools/            # Standalone scripts (graph generation, extract)
│   └── generate_graph_mermaid.py   # Regenerates docs/GRAPH.md via `uv run python tools/generate_graph_mermaid.py`
├── dev.sh / dev.ps1 # Dev launcher (backend + frontend in parallel)
├── format.ps1        # Full lint/format across backend + frontend
└── docker-compose.yml  # backend:8000, frontend:3000 (includes TeX Live)
```

## Non-obvious facts

- **All config uses `PDF2TEX_` prefix** — pydantic-settings reads from env. Never use a bare `DATABASE_URL` or similar.
- **LangGraph pipeline graph** lives in `docs/GRAPH.md` — auto-generated via `tools/generate_graph_mermaid.py`.
- **backend/Dockerfile includes TeX Live** for `pdflatex`. For dev, you need `pdflatex` on PATH (install TeX Live or MiKTeX).
- **OCR needs binary `tesseract` on PATH** — `pytesseract` is just the wrapper. Set `PDF2TEX_TESSERACT_CMD` if not in PATH.
- **Hot reload must scope `--reload-dir app`** — storage/ writes (figures, caches) trigger constant restarts otherwise.
- **PyTorch is resolved from a custom CUDA 12.4 index** in pyproject.toml, not PyPI. CPU torch won't be used.
- **Extra dependencies** use PEP 508 extras: `uv sync --extra tools`. Core deps alone won't enable extraction engines.
- Some OCR/math extras conflict on `cv2` (opencv-python vs opencv-python-headless). Install only what you need.
- **Frontend proxies** `/api` and `/ws` to `localhost:8000` via Vite config.
- **API keys are stored encrypted** (Fernet) in SQLite — `PDF2TEX_ENCRYPTION_KEY` is required.

## Commands

All `uv` commands run from `backend/`. All `bun` commands from `frontend/`.

```bash
# Backend
uv sync                              # core deps only
uv sync --dev                        # + dev deps (pytest, ruff, fastapi-cli)
uv sync --extra tools    # + extraction extras
uv run python -m app.main            # start (or uvicorn app.main:app --reload --reload-dir app)
uv run pytest tests/ -v              # all tests (mocked, no real LLM)
uv run pytest tests/ -v -m "not slow"  # fast tests only
uv run pytest tests/test_xxx.py::test_yyy -v  # single test
uv run ruff check .                  # lint
uv run ruff format .                 # auto-format

# Frontend
bun install
bun run dev           # dev server on :5173
bun run typecheck     # tsc --noEmit
bun run lint          # eslint
bun run test          # vitest
bun run build         # tsc -b && vite build

# Full-stack dev
.\dev.ps1             # two terminal windows (Windows)
bash dev.sh           # two processes (Linux/Mac)

# Full lint/format (after changes)
.\format.ps1          # ruff format → ruff lint → bun lint → bun tsc

# Docker
docker compose up --build
```

## Test quirks

- **conftest.py** loads `.env.test` via `load_dotenv(override=False)` before any app imports. Existing env vars take precedence.
- **Use `--real-llm`** flag + `PDF2TEX_TEST_PROVIDER`/`PDF2TEX_TEST_MODEL`/`PDF2TEX_TEST_API_KEY` for real LLM tests.
- **Known pre-existing failures**:
  - `test_full_graph_e2e` — 2 tests (`test_full_graph_compile_failure_then_judge_approves`, `test_full_graph_judge_disapproves_then_approves_on_revision`)
  - `test_multi_source` — 1 test crashes on Windows
- **Sandbox tests** (`@pytest.mark.sandbox`) check real engine availability (OCR, math, web, LLM). They auto-generate `report-sandbox.md`.
- **Test DB** is a temp SQLite file migrated automatically per session via the `_migrate_test_db` autouse fixture.
- **Known limitations**: test_multi_source has one known crash on Windows; test_full_graph_e2e has 2 pre-existing failures.
