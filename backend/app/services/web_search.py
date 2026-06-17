"""Web search service: abstract interface over Tavily, Perplexity, Wikipedia,
and custom HTTPX-based search APIs.

Each tool is a thin adapter that accepts a query string and returns a list of
``SearchResult`` objects. The caller (``research_node``) doesn't need to know
which provider is wired underneath.

- **Tavily**: uses the official ``tavily-python`` SDK (optional dep).
- **Perplexity**: uses direct HTTPX calls to the Sonar API (OpenAI-compatible,
  no extra package needed).
- **Wikipedia**: uses the free public REST API, no API key.
- **Custom HTTPX**: generic adapter configurable entirely via params.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import quote_plus

import httpx

from app.core.logging import get_logger

logger = get_logger("web_search")


@dataclass
class SearchResult:
    """A single result from a web search."""

    title: str
    url: str
    snippet: str
    # Full page content when available (after fetch/extract step).
    content: str = ""


# --------------------------------------------------------------------------- #
# Abstract base                                                                #
# --------------------------------------------------------------------------- #


class WebSearchAdapter:
    """Protocol all search adapters must follow."""

    tool_type: ClassVar[str] = ""

    def __init__(self, config: dict[str, Any]) -> None:
        self.api_key: str = config.get("api_key", "") or ""
        self.base_url: str = config.get("base_url", "") or ""
        self.params: dict[str, Any] = config.get("params", {}) or {}
        self.max_results: int = int(self.params.get("max_results", 5))

    async def search(self, query: str) -> list[SearchResult]:
        raise NotImplementedError

    async def fetch_page(self, url: str) -> str:
        """Download and extract readable text from a URL.

        Uses httpx to fetch the page and a simple heuristic to strip HTML.
        For production use, a proper HTML-to-text library (trafilatura,
        readability-lxml, or beautifulsoup4) would be better, but for now
        we keep it dependency-light and rely on the LLM to filter noise.
        """
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers={"User-Agent": "PDF2LaTeX/1.0"})
                resp.raise_for_status()
                text = resp.text
                # Crude HTML stripping: remove scripts, styles, then tags.
                text = re.sub(
                    r"<script[^>]*>.*?</script>",
                    " ",
                    text,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                text = re.sub(
                    r"<style[^>]*>.*?</style>",
                    " ",
                    text,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                # Cap at ~8000 chars to stay within LLM context budgets.
                return text[:8000]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to fetch page %s: %s", url, exc)
            return ""


# --------------------------------------------------------------------------- #
# Tavily adapter                                                               #
# --------------------------------------------------------------------------- #


class TavilyAdapter(WebSearchAdapter):
    """Tavily Search API — uses the official ``tavily-python`` SDK.

    Install: ``uv sync --extra research-tavily``
    Pip:      ``pip install tavily-python``

    Supports ``search_depth`` ("basic" | "advanced") and
    ``include_domains`` / ``exclude_domains`` via params (accepts
    a list of strings or a single comma-separated string).
    """

    tool_type: ClassVar[str] = "tavily"

    async def search(self, query: str) -> list[SearchResult]:
        if not self.api_key.strip():
            logger.warning("Tavily: no API key configured, skipping search.")
            return []

        try:
            from tavily import TavilyClient  # type: ignore[import-untyped]
        except ImportError:
            logger.error(
                "tavily-python is not installed. "
                "Install it with: uv sync --extra research-tavily"
            )
            return []

        client = TavilyClient(api_key=self.api_key)
        search_depth = str(self.params.get("search_depth", "advanced"))
        include_domains = _coerce_domain_list(self.params.get("include_domains"))
        exclude_domains = _coerce_domain_list(self.params.get("exclude_domains"))

        try:
            resp = await asyncio.to_thread(
                lambda: client.search(
                    query,
                    search_depth=search_depth,
                    max_results=self.max_results,
                    include_domains=include_domains or None,
                    exclude_domains=exclude_domains or None,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Tavily search failed for query '%s': %s", query, exc)
            return []

        results: list[SearchResult] = []
        for r in (resp.get("results") or [])[: self.max_results]:
            content = r.get("content", "") or ""
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=content[:500],
                    content=content[:8000],
                )
            )
        return results


# --------------------------------------------------------------------------- #
# Perplexity adapter (Sonar API)                                               #
# --------------------------------------------------------------------------- #


class PerplexityAdapter(WebSearchAdapter):
    """Perplexity Sonar API (https://docs.perplexity.ai).

    Requires a Perplexity API key. The Sonar models perform a live search
    and return a cited answer. We extract the citations' content for use
    as pseudo-documents.
    """

    tool_type: ClassVar[str] = "perplexity"

    async def search(self, query: str) -> list[SearchResult]:
        url = (self.base_url or "https://api.perplexity.ai/chat/completions").rstrip(
            "/"
        )
        model = self.params.get("model", "sonar-pro")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant. Answer the user's query "
                        "thoroughly with citations. Include as many relevant "
                        "facts and details as possible."
                    ),
                },
                {"role": "user", "content": query},
            ],
            "max_tokens": self.params.get("max_tokens", 4000),
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Perplexity returns a chat-style response with citations.
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})
        answer = message.get("content", "")
        citations: list[str] = data.get("citations", [])

        results: list[SearchResult] = []
        if answer.strip():
            results.append(
                SearchResult(
                    title=f"Perplexity: {query[:80]}",
                    url="",
                    snippet=answer[:500],
                    content=answer[:8000],
                )
            )
        # Also add cited URLs as individual results for potential page fetch.
        for cit_url in citations[: self.max_results - 1]:
            results.append(
                SearchResult(
                    title=cit_url.split("/")[-1] or cit_url,
                    url=cit_url,
                    snippet="",
                    content="",  # can be fetched later
                )
            )
        return results


# --------------------------------------------------------------------------- #
# Wikipedia adapter (free, no API key)                                         #
# --------------------------------------------------------------------------- #


class WikipediaAdapter(WebSearchAdapter):
    """Wikipedia API (no API key needed).

    Searches Wikipedia for articles matching the query and returns page
    extracts. Can also fetch full page content via the REST API.
    """

    tool_type: ClassVar[str] = "wikipedia"

    async def search(self, query: str) -> list[SearchResult]:
        # Use the Wikipedia REST API to search and get page summaries.
        base = self.base_url or "https://en.wikipedia.org/api/rest_v1"
        lang = self.params.get("language", "en")
        base = base.rstrip("/")

        # 1. Search for pages.
        params: dict[str, str] = {
            "action": "query",
            "list": "search",
            "format": "json",
            "srlimit": str(min(self.max_results + 5, 15)),
            "srsearch": query,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://{lang}.wikipedia.org/w/api.php", params=params
            )
            resp.raise_for_status()
            search_data = resp.json()

        pages = ((search_data.get("query") or {}).get("search") or [])[
            : self.max_results
        ]

        results: list[SearchResult] = []
        for page in pages:
            title = page.get("title", "")
            page_snippet = re.sub(r"<[^>]+>", "", page.get("snippet", "")).strip()

            # Fetch the page extract.
            page_id = page.get("pageid")
            content = ""
            if page_id:
                try:
                    extract_resp = await client.get(
                        f"https://{lang}.wikipedia.org/w/api.php",
                        params={
                            "action": "query",
                            "prop": "extracts",
                            "exintro": "1",
                            "explaintext": "1",
                            "pageids": str(page_id),
                            "format": "json",
                        },
                    )
                    extract_resp.raise_for_status()
                    extract_data = extract_resp.json()
                    pages_dict = (extract_data.get("query") or {}).get("pages") or {}
                    for _pid, pdata in pages_dict.items():
                        content = (pdata.get("extract") or "")[:8000]
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Failed to fetch Wikipedia extract for %s: %s", title, exc
                    )

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://{lang}.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                    snippet=page_snippet,
                    content=content,
                )
            )
        return results


# --------------------------------------------------------------------------- #
# Custom HTTPX adapter (generic search API)                                    #
# --------------------------------------------------------------------------- #


class CustomHttpxAdapter(WebSearchAdapter):
    """Generic HTTPX-based search adapter.

    Configured entirely through ``base_url`` and ``params``. The adapter
    POSTs a JSON payload to the configured endpoint and expects a JSON
    response with a ``results`` array.

    params can include:
      - ``headers``: extra HTTP headers (dict)
      - ``json_template``: a dict with ``{query}`` placeholder that gets
        interpolated before sending.
      - ``results_path``: dot-separated JSON path to the results array
        (e.g., ``"organic_results"`` or ``"data.items"``).
      - ``title_key`` / ``url_key`` / ``snippet_key`` / ``content_key``:
        keys within each result object.
      - ``method``: "POST" (default) or "GET".
      - ``query_param``: for GET requests, the query-string parameter name.
    """

    tool_type: ClassVar[str] = "custom_httpx"

    async def search(self, query: str) -> list[SearchResult]:
        method = (self.params.get("method") or "POST").upper()
        headers: dict[str, str] = dict(self.params.get("headers") or {})
        json_template: dict[str, Any] = dict(
            self.params.get("json_template") or {"q": "{query}"}
        )
        results_path: str = self.params.get("results_path") or "results"
        title_key: str = self.params.get("title_key") or "title"
        url_key: str = self.params.get("url_key") or "url"
        snippet_key: str = self.params.get("snippet_key") or "snippet"
        content_key: str = self.params.get("content_key") or "content"
        query_param: str = self.params.get("query_param") or "q"

        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(
                    self.base_url,
                    params={
                        query_param: query,
                        **(self.params.get("extra_params") or {}),
                    },
                    headers=headers,
                )
            else:
                body = _interpolate_template(json_template, query)
                resp = await client.post(self.base_url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Walk the results_path to find the results array.
        items: list[dict[str, Any]] = _walk_json(data, results_path)
        if not isinstance(items, list):
            logger.warning(
                "Custom HTTPX search: results_path '%s' did not resolve to a list",
                results_path,
            )
            items = []

        results: list[SearchResult] = []
        for r in items[: self.max_results]:
            results.append(
                SearchResult(
                    title=str(r.get(title_key, "")),
                    url=str(r.get(url_key, "")),
                    snippet=str(r.get(snippet_key, ""))[:500],
                    content=str(r.get(content_key, ""))[:8000],
                )
            )
        return results


# --------------------------------------------------------------------------- #
# Factory                                                                      #
# --------------------------------------------------------------------------- #


def get_search_adapter(config: dict[str, Any]) -> WebSearchAdapter | None:
    """Create a search adapter from a web tool config dict.

    ``config`` must contain at least ``tool_type``. Returns ``None`` for
    unknown tool types.
    """
    tool_type = (config.get("tool_type") or "").lower()
    adapters: dict[str, type[WebSearchAdapter]] = {
        "tavily": TavilyAdapter,
        "perplexity": PerplexityAdapter,
        "wikipedia": WikipediaAdapter,
        "custom_httpx": CustomHttpxAdapter,
    }
    cls = adapters.get(tool_type)
    if cls is None:
        logger.warning("Unknown web search tool type: %s", tool_type)
        return None
    return cls(config)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _interpolate_template(template: dict, query: str) -> dict:
    """Recursively replace ``{query}`` in string values."""
    out: dict[str, Any] = {}
    for k, v in template.items():
        if isinstance(v, str):
            out[k] = v.replace("{query}", query)
        elif isinstance(v, dict):
            out[k] = _interpolate_template(v, query)
        elif isinstance(v, list):
            out[k] = [
                _interpolate_template(item, query) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            out[k] = v
    return out


def _walk_json(data: Any, path: str) -> Any:
    """Walk a dot-separated path into a JSON object (e.g. ``'data.results'``)."""
    current = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            try:
                current = current[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _coerce_domain_list(
    value: str | list[str] | None,
) -> list[str] | None:
    """Normalise a domain filter to ``list[str] | None``.

    Accepts a list of domains, a comma-separated string, or ``None``.
    Returns ``None`` when the input is empty/falsy.
    """
    if value is None:
        return None
    if isinstance(value, list):
        cleaned = [d.strip() for d in value if d.strip()]
        return cleaned if cleaned else None
    if isinstance(value, str):
        parts = [d.strip() for d in value.split(",") if d.strip()]
        return parts if parts else None
    return None
