"""Tests for ``app.services.web_extractor.fetch_and_extract``.

Each test controls the HTTP response via ``httpx.AsyncClient`` mock, then uses
``types.ModuleType`` + ``sys.modules`` to create proper fake modules that the
import system will accept. This reliably controls the extraction path regardless
of what packages are actually installed.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.web_extractor import fetch_and_extract

# ── helpers ────────────────────────────────────────────────────────────────


def _mock_httpx(text: str, raise_for_status_side_effect=None):
    """Return an ``AsyncMock`` that mimics ``httpx.AsyncClient`` returning *text*."""
    mock_resp = MagicMock()
    mock_resp.text = text
    mock_resp.raise_for_status = MagicMock(side_effect=raise_for_status_side_effect)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get.return_value = mock_resp
    return mock_client


def _register_fake_module(monkeypatch, name: str, **attrs) -> types.ModuleType:
    """Create and register a ``types.ModuleType`` with *attrs* in ``sys.modules``.

    Uses ``monkeypatch.setitem`` so the original entry is restored after the test.
    """
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


# ── tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trafilatura_succeeds(monkeypatch) -> None:
    """When trafilatura is available, it returns clean text."""
    html = (
        "<html><body>"
        "<article><h1>Test Article</h1><p>Hello world.</p></article>"
        "<nav>Menu</nav>"
        "<footer>Copyright</footer>"
        "</body></html>"
    )

    _register_fake_module(
        monkeypatch,
        "trafilatura",
        extract=lambda h, **kw: "[TRAFILATURA] Clean article text here.",
    )

    with patch("httpx.AsyncClient", return_value=_mock_httpx(html)):
        text = await fetch_and_extract("https://example.com", max_chars=10_000)

    assert text == "[TRAFILATURA] Clean article text here."


@pytest.mark.asyncio
async def test_trafilatura_empty_falls_back_to_bs4(monkeypatch) -> None:
    """trafilatura returns empty → BeautifulSoup fallback."""
    html = "<html><body><h1>Page</h1><p>Some text.</p></body></html>"

    _register_fake_module(
        monkeypatch,
        "trafilatura",
        extract=lambda h, **kw: "",
    )

    with patch("httpx.AsyncClient", return_value=_mock_httpx(html)):
        text = await fetch_and_extract("https://example.com", max_chars=10_000)

    # bs4 fallback includes all text from the page (preserves nav/footer too).
    assert "Page" in text
    assert "Some text" in text


@pytest.mark.asyncio
async def test_trafilatura_import_error_falls_back_to_bs4(
    monkeypatch,
) -> None:
    """trafilatura not installed → BeautifulSoup fallback."""
    html = "<html><body><h1>Fallback</h1><p>Works.</p></body></html>"

    monkeypatch.setitem(sys.modules, "trafilatura", None)

    with patch("httpx.AsyncClient", return_value=_mock_httpx(html)):
        text = await fetch_and_extract("https://example.com", max_chars=10_000)

    assert "Fallback" in text
    assert "Works" in text


@pytest.mark.asyncio
async def test_both_trafilatura_and_bs4_fail_returns_raw_html(
    monkeypatch,
) -> None:
    """Both trafilatura and BeautifulSoup fail → raw HTML returned."""
    html = "<html><body>Raw content.</body></html>"

    monkeypatch.setitem(sys.modules, "trafilatura", None)
    monkeypatch.setitem(sys.modules, "bs4", None)

    with patch("httpx.AsyncClient", return_value=_mock_httpx(html)):
        text = await fetch_and_extract("https://example.com", max_chars=10_000)

    # Raw HTML returned.
    assert "Raw content" in text


@pytest.mark.asyncio
async def test_max_chars_truncation(monkeypatch) -> None:
    """Text is truncated to *max_chars*."""
    long_html = "<html><body>" + "A" * 5000 + "</body></html>"

    # Make trafilatura unavailable → bs4 fallback (which preserves all text).
    monkeypatch.setitem(sys.modules, "trafilatura", None)

    with patch("httpx.AsyncClient", return_value=_mock_httpx(long_html)):
        text = await fetch_and_extract("https://example.com", max_chars=200)

    assert len(text) <= 200


@pytest.mark.asyncio
async def test_http_error_raises(monkeypatch) -> None:
    """HTTP errors are not swallowed — they propagate to the caller."""
    monkeypatch.setitem(sys.modules, "trafilatura", None)

    mock_client = _mock_httpx("", raise_for_status_side_effect=RuntimeError("HTTP 500"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await fetch_and_extract("https://example.com")


@pytest.mark.asyncio
async def test_follow_redirects_is_true(monkeypatch) -> None:
    """The httpx client is configured with follow_redirects=True."""
    _register_fake_module(
        monkeypatch,
        "trafilatura",
        extract=lambda h, **kw: "[MOCKED_OK]",
    )

    mock_client = _mock_httpx("<html>ok</html>")

    with patch("httpx.AsyncClient", return_value=mock_client):
        await fetch_and_extract("https://short.link")

    # Verify the get call had follow_redirects=True.
    call_kwargs = mock_client.__aenter__.return_value.get.call_args
    assert call_kwargs is not None
    _, kwargs = call_kwargs
    assert kwargs.get("follow_redirects") is True
