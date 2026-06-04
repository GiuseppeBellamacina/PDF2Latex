# PDF2LaTeX

Trasforma **N PDF** in un unico documento **LaTeX** organico e completo, in modo
intelligente e personalizzato, tramite una pipeline agentica (LangGraph) e una UI
React moderna, minimale e monocromatica.

Ispirato al workflow di [EPUB-Translator](https://github.com/GiuseppeBellamacina/EPUB-Translator).

## Architettura

```
┌──────────────┐     WebSocket / REST     ┌────────────────────────────────────┐
│  Frontend    │ ───────────────────────► │  Backend (FastAPI)                 │
│  React+Vite  │                          │                                    │
│  Tailwind    │                          │  Estrazione PDF (PyMuPDF)          │
└──────────────┘                          │            │                       │
                                          │   LangGraph pipeline:              │
                                          │   analyze (fan-out per PDF)        │
                                          │      → plan (struttura globale)    │
                                          │      → write (fan-out, parallelo)  │
                                          │      → review + pdflatex (retry)   │
                                          │            │                       │
                                          │   SQLite (progetti, provider)      │
                                          └────────────────────────────────────┘
```

### Agenti

| Agente   | Ruolo                                                                 |
| -------- | --------------------------------------------------------------------- |
| Analyzer | Analizza ogni PDF (riassunto, argomenti, formule, figure) — parallelo |
| Planner  | Unisce le analisi + il prompt utente in una struttura globale         |
| Writer   | Scrive il LaTeX di ogni sezione — parallelo                           |
| Reviewer | Corregge errori di compilazione e incoerenze (loop con pdflatex)      |

## Avvio rapido (sviluppo)

### Backend

```pwsh
cd backend
uv sync
copy .env.example .env   # imposta PDF2TEX_ENCRYPTION_KEY
uv run python -m app.main
```

### Frontend

```pwsh
cd frontend
bun install
bun run dev
```

Apri `http://localhost:5173`. Configura un provider in **Provider**
(o usa quello `fake` per una prova offline), carica i PDF e genera.

## Avvio con Docker

```pwsh
docker compose up --build
```

Frontend su `http://localhost:3000`, backend su `http://localhost:8000`.
L'immagine backend include TeX Live per la compilazione `pdflatex`.

## Provider supportati

`openai`, `anthropic`, `ollama`, `custom` (OpenAI-compatibile) e `fake` (offline).
Le chiavi API sono salvate **cifrate** (Fernet) nel database locale.

## Personalizzazione

- **Prompt utente**: campo libero per indicare taglio, focus, lunghezza, ordine.
- **Estrattori**: `pymupdf` (default), `docling`, `markitdown` (extra opzionali),
  OCR fallback con `pytesseract`.
- **Lingua**: italiano (default) o inglese.
