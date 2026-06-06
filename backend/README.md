# PDF2LaTeX — Backend

Agentic backend (FastAPI + LangGraph) that turns N PDFs into a single,
comprehensive LaTeX document in Italian (or another language).

## Pipeline

```
extract (PyMuPDF) -> analyze (fan-out per PDF) -> plan (global structure)
                  -> write (fan-out per section, parallel) -> review + compile (pdflatex)
```

## Setup

```pwsh
uv sync                 # core deps
uv sync --extra ocr     # optional OCR fallback (pytesseract)
copy .env.example .env  # configure PDF2TEX_* variables
uv run python -m app.main
```

> **Hot reload (dev):** if you start uvicorn with `--reload`, scope it to the
> source folder so writes to `storage/` (figures, logs, Docling cache) don't
> trigger constant restarts:
>
> ```pwsh
> uv run uvicorn app.main:app --reload --reload-dir app
> ```

> **OCR:** `pytesseract` is only a wrapper — the **Tesseract binary** must be
> installed and on `PATH`, otherwise OCR is silently skipped (the API reports
> `ocr: false`). On Windows: `winget install UB-Mannheim.TesseractOCR`, then
> install the language packs you need (e.g. `ita`, `eng`). Configure languages
> with `PDF2TEX_OCR_LANG` (default `ita+eng`).

The API is served at `http://localhost:8000` (`/api/health`, `/api/providers`,
`/api/projects`, WebSocket `/ws/generate/{project_id}`).

## Providers

LLM providers (openai / anthropic / ollama / custom / **fake**) are configured
at runtime via `/api/providers`. API keys are stored **encrypted** (Fernet).
The `fake` provider lets you exercise the full pipeline offline without a key.
