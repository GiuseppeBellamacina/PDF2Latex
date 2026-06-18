"""URL fetching and text extraction — separate from the runner so it can be
tested independently and reused across the codebase (runner, web_search, etc.).

Strategy (best-effort, fails gracefully):
  1. Fetch the page with httpx (30 s timeout, follow redirects).
  2. Try trafilatura (high-quality boilerplate removal, optional dep).
  3. Fall back to BeautifulSoup (always available via docling).
  4. Last resort: return the raw HTML.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("web_extractor")


async def fetch_and_extract(url: str, max_chars: int | None = None) -> str:
    """Download *url* and return cleaned readable text.

    Parameters
    ----------
    url:
        The page to fetch.
    max_chars:
        If set, truncate the returned text to at most *max_chars* characters.
        When ``None`` (the default), the ``ANALYZER_CHUNK_CHARS × ANALYZER_MAX_CHUNKS``
        limit from the project settings is applied.
    """
    if max_chars is None:
        max_chars = settings.analyzer_chunk_chars * settings.analyzer_max_chunks

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        html = resp.text

    # 1. trafilatura — best quality, removes nav / footer / ads
    try:
        from trafilatura import extract

        text = (
            extract(
                html,
                include_links=False,
                include_images=False,
                include_tables=True,
            )
            or ""
        )
        if not text.strip():
            raise ValueError("trafilatura returned empty")
        logger.debug("URL %s: extracted %d chars via trafilatura", url, len(text))
        return text[:max_chars]
    except Exception:
        logger.debug("trafilatura unavailable or empty for %s, falling back", url)

    # 2. BeautifulSoup — always available (transitive dep of docling)
    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        logger.debug("URL %s: extracted %d chars via BeautifulSoup", url, len(text))
        return text[:max_chars]
    except Exception:
        logger.debug("BeautifulSoup failed for %s, returning raw HTML", url)

    # 3. Raw HTML — last resort
    return html[:max_chars]
