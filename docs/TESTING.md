# Testing Guide

This document explains how to run the PDF2LaTeX backend test suite — from fast
unit tests to full end-to-end runs with a real LLM and live web search backends.

## Quick start

```bash
cd backend

# Run every test that does NOT need a real LLM or API keys (fast, offline)
uv run python -m pytest tests/ -v

# Same, but skip slow-marked tests explicitly
uv run python -m pytest tests/ -v -m "not slow"
```

Tests are discovered automatically from `backend/tests/`.  All async tests use
`pytest-asyncio` with `asyncio_mode = auto` (configured in `pyproject.toml`).

---

## Test file overview

| File | What it covers | Needs `--real-llm`? |
|------|---------------|---------------------|
| `test_api_patch.py` | PATCH endpoint, `research_mode` / `web_tool_ids` validation | No |
| `test_bibliography.py` | BibTeX generation, citation key dedup | No |
| `test_citation_auditor.py` | Citation compliance checks | No |
| `test_coherence.py` | Cross-chapter coherence checks | No |
| `test_diamond_merge.py` | Diamond merge in the LangGraph graph | No |
| `test_full_graph_e2e.py` | Full pipeline (mocked LLM) — analyze → plan → write → review | No |
| `test_multi_source.py` | Multi-source extraction, E2E with real files | No |
| `test_pipeline.py` | Pipeline stages, tool resolution | No |
| `test_planner.py` | Deterministic source-order sorting in `plan_document` | No |
| `test_prompts.py` | Prompt templates, token budget checks | No |
| `test_runner_e2e.py` | Runner orchestration E2E | No |
| `test_text_cleaning.py` | Text cleaning / normalisation utilities | No |
| **`test_web_agent.py`** | **Web Agent, Tavily, Perplexity, Wikipedia** | **Yes** (some) |
| `test_web_extractor.py` | URL fetching and HTML extraction | No |
| `test_writer_context.py` | Context sharing between consecutive sections | No |

---

## Running with a real LLM (`--real-llm`)

Some tests in `test_web_agent.py` (and the full graph E2E when explicitly
configured) can run against a **real LLM provider** instead of mocks.  Pass the
`--real-llm` flag and set a few environment variables:

```bash
# PowerShell (Windows)
$env:PDF2TEX_TEST_PROVIDER = "openai"
$env:PDF2TEX_TEST_MODEL = "gpt-4o-mini"
$env:PDF2TEX_TEST_API_KEY = "sk-..."

# Bash / Zsh (Linux, macOS, WSL)
export PDF2TEX_TEST_PROVIDER="openai"
export PDF2TEX_TEST_MODEL="gpt-4o-mini"
export PDF2TEX_TEST_API_KEY="sk-..."

# Run only the real-LLM tests
uv run python -m pytest tests/test_web_agent.py -v --real-llm
```

### Environment variables for real LLM

| Variable | Required? | Default | Description |
|----------|-----------|---------|-------------|
| `PDF2TEX_TEST_PROVIDER` | No | `openai` | Provider id: `openai`, `anthropic`, `deepseek`, `ollama`, etc. |
| `PDF2TEX_TEST_MODEL` | No | `gpt-4o-mini` | Model name. Keep it small for fast, cheap tests. |
| `PDF2TEX_TEST_API_KEY` | No | Provider default | API key. Falls back to the provider's SDK env var (e.g. `OPENAI_API_KEY`). |
| `PDF2TEX_TEST_API_BASE` | No | Provider default | Custom API base URL (e.g. `http://localhost:11434` for Ollama). |

Any test that needs a real LLM checks `if not use_real_llm: pytest.skip(...)`,
so when you run without `--real-llm` those tests are safely skipped.

---

## Sandbox tests (engine availability)

The sandbox tests (`tests/test_sandbox.py`) are a separate suite that verifies all
OCR, math, structure, web search, and LLM engines work correctly with real test assets.
Marked `@pytest.mark.sandbox`; network tests additionally `@pytest.mark.network` and `@pytest.mark.slow`.

| Category | Count | Engines |
|----------|-------|---------|
| 🖼️ OCR | 2 | Tesseract, RapidOCR |
| 🧮 Math | 1 | pix2tex |
| 📐 Structure | 1 | Docling |
| 🌐 Web | 5 | Wikipedia, Tavily, Perplexity, Web Agent, Page Fetch |
| 🤖 LLM | 2 | Fake (offline), Real (configurable) |

```bash
# Local only (no network, no API keys):
uv run pytest tests/test_sandbox.py -v -m "sandbox and not network"

# All sandbox tests (local + network):
uv run pytest tests/test_sandbox.py -v -m sandbox --runxfail

# With JUnit XML:
uv run pytest tests/test_sandbox.py -m sandbox --runxfail --junitxml=report-sandbox.xml
```

### Markdown report

Running any sandbox test automatically generates `report-sandbox.md` in the backend root.
The report includes:
- Timestamp and duration
- Summary counts (passed/failed/skipped)
- Per-category tables with status, test name, duration, stdout, stderr, warnings, errors
- Re-run commands in a footer

This is driven by a conftest plugin using `pytest_sessionfinish`; no extra flags needed.

---

## Web search tool tests

The web agent tests (`test_web_agent.py`) exercise four backends:

| Backend | Needs API key? | Env var |
|---------|---------------|---------|
| **Wikipedia** | No — always available | `PDF2TEX_TEST_WIKI_LANG` (optional, default `en`) |
| **Tavily** | Yes | `PDF2TEX_TEST_TAVILY_KEY` |
| **Perplexity** | Yes | `PDF2TEX_TEST_PERPLEXITY_KEY` |

### Wikipedia (free, always works)

```bash
uv run python -m pytest tests/test_web_agent.py -v --real-llm
```

Wikipedia tests run automatically — no API key needed.  Optionally override the
language:

```bash
export PDF2TEX_TEST_WIKI_LANG="it"
```

### Tavily

```bash
export PDF2TEX_TEST_TAVILY_KEY="tvly-..."
uv run python -m pytest tests/test_web_agent.py -v --real-llm
```

Tests that use the Tavily adapter:

- `test_tavily_adapter_real_api` — basic results structure
- `test_tavily_adapter_content_rich_results` — asserts non-empty `content` inline

### Perplexity

```bash
export PDF2TEX_TEST_PERPLEXITY_KEY="pplx-..."
uv run python -m pytest tests/test_web_agent.py -v --real-llm
```

Tests that use the Perplexity adapter:

- `test_perplexity_adapter_content_rich_results` — asserts non-empty `content` inline

### All three backends together

Set all the env vars and the hybrid / multi-adapter tests will use every
available backend:

```bash
export PDF2TEX_TEST_PROVIDER="openai"
export PDF2TEX_TEST_MODEL="gpt-4o-mini"
export PDF2TEX_TEST_API_KEY="sk-..."
export PDF2TEX_TEST_TAVILY_KEY="tvly-..."
export PDF2TEX_TEST_PERPLEXITY_KEY="pplx-..."

uv run python -m pytest tests/test_web_agent.py -v --real-llm
```

Tests that combine multiple adapters:

- `test_run_web_agent_real_llm_hybrid_wikipedia` — LLM + Wikipedia
- `test_run_web_agent_real_llm_hybrid_multi_adapter` — LLM + Wikipedia + Tavily
- `test_run_web_agent_real_llm_search_tools` — Web Agent with `_resolved_web_tools`
- `test_run_web_agent_real_llm_pure` — pure LLM web search (no external tools)
- `test_run_web_agent_real_llm_search_tools_only` — search tools only (no LLM planning)

---

## Common patterns

### Run a single test

```bash
uv run python -m pytest tests/test_planner.py::test_deterministic_source_order_sorts_by_earliest_document -v
```

### Run a single file

```bash
uv run python -m pytest tests/test_web_agent.py -v
```

### Skip slow tests (real LLM & real web tools)

```bash
uv run python -m pytest tests/ -v -m "not slow"
```

### All tests (unit + sandbox local)

```bash
uv run pytest tests/ -v -m "not slow"
```

### Show skipped tests

```bash
uv run python -m pytest tests/ -v -rs
```

### Run with short tracebacks on failure

```bash
uv run python -m pytest tests/ -v --tb=short
```

### Quiet mode — just the counts

```bash
uv run python -m pytest tests/ -q
```

---

## Current state (reference)

```
tests/
├── assets/                     # test.png, test.pdf — real test assets
├── conftest.py                  # Fixtures: real_llm_config, wikipedia_adapter,
│                                #   tavily_adapter, perplexity_adapter,
│                                #   resolved_web_tools, sample plans, mock data
│                                #   + Markdown report plugin (pytest_sessionfinish)
├── test_api_patch.py            # 7 tests
├── test_bibliography.py         # 16 tests
├── test_citation_auditor.py     # 16 tests
├── test_coherence.py            # 9 tests
├── test_diamond_merge.py        # 18 tests
├── test_full_graph_e2e.py       # 11 tests (2 known failures — pre-existing)
├── test_multi_source.py         # 33 tests (1 known crash on Windows)
├── test_pipeline.py             # 13 tests
├── test_planner.py              # 6 tests
├── test_prompts.py              # 27 tests
├── test_runner_e2e.py           # 1 test
├── test_sandbox.py              # 17 tests (sandbox — engine availability)
├── test_text_cleaning.py        # 14 tests
├── test_web_agent.py            # 40 tests (7 need --real-llm + API keys)
├── test_web_extractor.py        # 7 tests
└── test_writer_context.py       # 18 tests
Total: ~250 tests collected
```

---

## Tips

- **Use a cheap model** for `--real-llm` tests: `gpt-4o-mini`, `claude-3-haiku`,
  or a local Ollama model (`llama3.2`, `mistral`).
- Set `PDF2TEX_TEST_API_BASE="http://localhost:11434"` when testing with Ollama
  and `PDF2TEX_TEST_PROVIDER="ollama"`.
- The test database is a temporary SQLite file created in the project directory.
  It is migrated automatically before every test session via the
  `_migrate_test_db` fixture (`scope="session", autouse=True`).
- `@pytest.mark.slow` is applied to all real-LLM and real-web-tool tests.
  Use `-m "not slow"` to skip them in CI or during fast iteration.
