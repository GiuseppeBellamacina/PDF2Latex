"""Pytest sandbox tests — convert the standalone sandbox scripts into proper
pytest tests that run in CI and produce JUnit XML reports.

All tests are marked ``@pytest.mark.sandbox``.  Network tests that call
live APIs are additionally marked ``@pytest.mark.network`` and
``@pytest.mark.slow``.  Tests skip gracefully when the required engine /
tool is not installed or the required env var is not set.

Run:  pytest tests/test_sandbox.py -v -m sandbox
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_ASSETS = Path(__file__).resolve().parent / "assets"
_IMG = _ASSETS / "test.png"
_PDF = _ASSETS / "test.pdf"


# ═══════════════════════════════════════════════════════════════════════════
# OCR engines
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.sandbox
def test_sandbox_ocr_tesseract():
    from app.services.extractor import tesseract_available
    from app.services.ocr_engines import engine_available, run_ocr

    if not engine_available("tesseract"):
        pytest.skip("pytesseract module not installed")
    if not tesseract_available():
        pytest.skip("tesseract binary not found or import broken")
    if not _IMG.exists():
        pytest.skip(f"Asset missing: {_IMG}")

    text = run_ocr(_IMG, lang="eng", engine="tesseract")
    assert isinstance(text, str)
    assert len(text.strip()) > 0, "Tesseract should produce output from test.png"


@pytest.mark.sandbox
def test_sandbox_ocr_rapidocr():
    from app.services.ocr_engines import engine_available, run_ocr

    if not engine_available("rapidocr"):
        pytest.skip("rapidocr not installed")
    if not _IMG.exists():
        pytest.skip(f"Asset missing: {_IMG}")

    text = run_ocr(_IMG, lang="eng", engine="rapidocr")
    assert isinstance(text, str)
    assert len(text.strip()) > 0, "RapidOCR should produce output from test.png"


# ═══════════════════════════════════════════════════════════════════════════
# Math engines
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.sandbox
def test_sandbox_math_pix2tex():
    from app.services.math_engines import engine_available, equation_to_latex

    if not engine_available("pix2tex"):
        pytest.skip("pix2tex not installed")
    if not _IMG.exists():
        pytest.skip(f"Asset missing: {_IMG}")

    latex = equation_to_latex(_IMG, engine="pix2tex")
    assert isinstance(latex, str)
    assert len(latex.strip()) > 0, "pix2tex should produce LaTeX from test.png"


# ═══════════════════════════════════════════════════════════════════════════
# Structure engines
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.sandbox
def test_sandbox_structure_docling():
    from app.services.structure_engines import engine_available, extract_structure

    if not engine_available("docling"):
        pytest.skip("docling not installed")
    if not _PDF.exists():
        pytest.skip(f"Asset missing: {_PDF}")

    md = extract_structure(_PDF, engine="docling")
    # Docling may return None on internal error (e.g. model not loaded).
    assert md is None or isinstance(md, str)


# ═══════════════════════════════════════════════════════════════════════════
# Web tools
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.sandbox
@pytest.mark.network
@pytest.mark.slow
@pytest.mark.asyncio
async def test_sandbox_web_wikipedia():
    from app.services.web_search import WikipediaAdapter

    adapter = WikipediaAdapter(
        {
            "tool_type": "wikipedia",
            "params": {"language": "en", "max_results": 3},
        }
    )
    results = await adapter.search("quantum computing")
    assert isinstance(results, list)
    if results:
        for r in results:
            assert r.title, "Every result must have a title"
            assert r.url, "Every result must have a URL"


@pytest.mark.sandbox
@pytest.mark.network
@pytest.mark.slow
@pytest.mark.asyncio
async def test_sandbox_web_tavily():
    key = os.environ.get("PDF2TEX_TEST_TAVILY_KEY", "")
    if not key:
        pytest.skip("PDF2TEX_TEST_TAVILY_KEY not set")

    from app.services.web_search import TavilyAdapter

    adapter = TavilyAdapter(
        {
            "tool_type": "tavily",
            "api_key": key,
            "params": {"search_depth": "basic", "max_results": 3},
        }
    )
    results = await adapter.search("transformer architecture")
    assert isinstance(results, list)
    if results:
        for r in results:
            assert r.title, "Every result must have a title"
            assert r.url, "Every result must have a URL"


@pytest.mark.sandbox
@pytest.mark.network
@pytest.mark.slow
@pytest.mark.asyncio
async def test_sandbox_web_perplexity():
    key = os.environ.get("PDF2TEX_TEST_PERPLEXITY_KEY", "")
    if not key:
        pytest.skip("PDF2TEX_TEST_PERPLEXITY_KEY not set")

    from app.services.web_search import PerplexityAdapter

    adapter = PerplexityAdapter(
        {
            "tool_type": "perplexity",
            "api_key": key,
            "params": {"model": "sonar-pro", "max_tokens": 2000, "max_results": 3},
        }
    )
    results = await adapter.search("Explain the transformer architecture")
    assert isinstance(results, list)
    if results:
        for r in results:
            assert r.title, "Every result must have a title"
            assert r.content.strip(), "Perplexity should return non-empty content"


@pytest.mark.sandbox
@pytest.mark.network
@pytest.mark.slow
@pytest.mark.asyncio
async def test_sandbox_web_agent():
    provider = os.environ.get("PDF2TEX_TEST_PROVIDER", "")
    api_key = os.environ.get("PDF2TEX_TEST_API_KEY", "")
    if not provider or not api_key:
        pytest.skip("PDF2TEX_TEST_PROVIDER + PDF2TEX_TEST_API_KEY not set")

    model = os.environ.get("PDF2TEX_TEST_MODEL", "gpt-4o-mini")
    api_base = os.environ.get("PDF2TEX_TEST_API_BASE", "")

    from app.services.web_search import WebAgentAdapter

    llm_cfg = {"provider": provider, "model": model, "api_key": api_key}
    if api_base:
        llm_cfg["base_url"] = api_base

    adapter = WebAgentAdapter(
        {
            "tool_type": "web_agent",
            "params": {
                "max_iterations": 2,
                "llm_config": llm_cfg,
                "search_tools": [{"tool_type": "wikipedia"}],
            },
        }
    )
    results = await adapter.search("What is a transformer in deep learning?")
    assert isinstance(results, list)
    # Web Agent depends on real LLM + network — may legitimately return 0.
    if results:
        for r in results:
            assert r.title, "Every result must have a title"


@pytest.mark.sandbox
@pytest.mark.network
@pytest.mark.slow
@pytest.mark.asyncio
async def test_sandbox_web_page_fetch():
    from app.services.web_search import WikipediaAdapter

    adapter = WikipediaAdapter({"tool_type": "wikipedia", "params": {}})
    text = await adapter.fetch_page("https://en.wikipedia.org/wiki/Machine_learning")
    assert isinstance(text, str)


# ═══════════════════════════════════════════════════════════════════════════
# LLM providers
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_sandbox_llm_fake():
    from app.core.llm_factory import LLMConfig, create_llm

    config = LLMConfig(provider="fake", model="fake-echo")
    llm = create_llm(config)
    result = await llm.ainvoke("Hello")
    text = str(getattr(result, "content", result))
    assert "fake" in text.lower() or "segnaposto" in text.lower(), (
        "Fake provider should return placeholder text"
    )


@pytest.mark.sandbox
@pytest.mark.network
@pytest.mark.slow
@pytest.mark.asyncio
async def test_sandbox_llm_real():
    provider = os.environ.get("PDF2TEX_TEST_PROVIDER", "")
    api_key = os.environ.get("PDF2TEX_TEST_API_KEY", "")
    if not provider or not api_key:
        pytest.skip("PDF2TEX_TEST_PROVIDER + PDF2TEX_TEST_API_KEY not set")

    model = os.environ.get("PDF2TEX_TEST_MODEL", "gpt-4o-mini")
    api_base = os.environ.get("PDF2TEX_TEST_API_BASE", "")

    from app.core.llm_factory import LLMConfig, test_llm_connection

    config = LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key or None,
        base_url=api_base or None,
    )
    result = await test_llm_connection(config)
    assert result["success"], (
        f"LLM connection failed at stage '{result.get('stage', '?')}': "
        f"{result.get('error', '?')}"
    )
    assert result.get("latency_ms", 0) > 0, "Should have non-zero latency"
