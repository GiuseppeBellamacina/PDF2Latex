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

The API is served at `http://localhost:8000` (`/api/health`, `/api/providers`,
`/api/projects`, WebSocket `/ws/generate/{project_id}`).

## Providers

LLM providers (openai / anthropic / ollama / custom / **fake**) are configured
at runtime via `/api/providers`. API keys are stored **encrypted** (Fernet).
The `fake` provider lets you exercise the full pipeline offline without a key.
