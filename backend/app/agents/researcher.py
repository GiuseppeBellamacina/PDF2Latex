"""Research agent: orchestrates the multi-node Web Agent and maps its output
to ``SourceAnalysis`` dicts compatible with the existing analysis→plan→write pipeline.

The heavy lifting is done by the multi-node Web Agent LangGraph in
``web_agent.py``: planner → parallel specialised search nodes (Tavily,
Perplexity, Wikipedia, Arxiv, custom URLs) → deduplicator → merger →
evaluator → loop. This module is a thin orchestration layer that:

1. Builds ``WebSearchAdapter`` instances from the project's web tool configs.
2. Calls ``run_web_agent()`` for the topic.
3. Maps ``SearchResult`` objects (now carrying ``authors``, ``year``,
   ``venue`` citation metadata) to ``SourceAnalysis`` dicts.
4. Returns analyses ready for the planner node.

Source links are preserved in ``references``, so the writer can cite them
as proper bibliography entries in the final LaTeX document.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.web_search import SearchResult, get_search_adapter

logger = get_logger("researcher")


async def research_topic(
    topic: str,
    language: str,
    llm_config: dict[str, Any],
    web_tool_configs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Run the multi-node Web Agent and map results to SourceAnalysis dicts.

    Returns a tuple of ``(analyses, raw_results)`` where:
    - ``analyses`` are ``SourceAnalysis``-compatible dicts;
    - ``raw_results`` are lightweight dicts ``{title, url, source}`` for the
      front-end preview of found sources.
    """
    from app.agents.web_agent import run_web_agent

    # Build adapters from the project's web tool configs.
    adapters = []
    for config in web_tool_configs:
        tool_type = (config.get("tool_type") or "").lower()
        # The web_agent orchestrator itself is not a search adapter.
        if tool_type == "web_agent":
            continue
        adapter = get_search_adapter(config)
        if adapter is not None:
            adapters.append(adapter)
        else:
            logger.warning("No adapter for tool_type=%s; skipping", tool_type)

    tool_types = [a.tool_type for a in adapters]
    logger.info(
        "Research: %d adapters for topic '%s': %s",
        len(adapters),
        topic[:80],
        ", ".join(tool_types) if tool_types else "none",
    )

    # Run the multi-node Web Agent.
    results: list[SearchResult] = await run_web_agent(
        query=topic,
        llm_config=llm_config,
        max_iterations=3,
        search_adapters=adapters if adapters else None,
    )

    if not results:
        logger.warning("Research: no results for topic '%s'", topic[:80])
        return [], []

    # Build raw result previews for the front-end (title, url, source).
    raw_previews: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for r in results:
        if not r.title.strip():
            continue
        url = r.url.strip()
        key = url or r.title.strip().lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        raw_previews.append(
            {
                "title": r.title[:200],
                "url": url,
                "source": r.venue or _domain_from_url(url) or "web",
            }
        )

    # Map SearchResults to SourceAnalysis dicts.
    analyses = list(_results_to_analyses(results, topic, language))
    return analyses, raw_previews


def _results_to_analyses(
    results: list[SearchResult],
    topic: str,
    language: str,
) -> list[dict[str, Any]]:
    """Convert collected SearchResults into SourceAnalysis-compatible dicts.

    Groups results by tool type / source, extracts topics from snippets,
    and builds a ``references`` list with full citation metadata including
    the source URL — so the downstream bibliography and citation audit
    can pick them up as proper \\cite entries.
    """
    # Group results by source (venue or tool origin).
    groups: dict[str, list[SearchResult]] = {}
    for r in results:
        # Use venue as group key; fall back to domain from URL.
        key = r.venue or _domain_from_url(r.url) or "web"
        groups.setdefault(key, []).append(r)

    analyses: list[dict[str, Any]] = []
    for source, group in groups.items():
        # Build a combined summary from the group's content.
        summaries: list[str] = []
        topics_list: list[str] = []
        keywords: set[str] = set()
        references: list[dict[str, str]] = []

        for r in group:
            if r.snippet:
                summaries.append(r.snippet[:600])
            # Extract potential topics from title and snippet.
            title = r.title.strip()
            if title and len(title) > 5:
                topics_list.append(title[:120])

            # Build a reference entry with full citation metadata.
            ref: dict[str, str] = {}
            if r.authors:
                ref["authors"] = r.authors
            else:
                ref["authors"] = _domain_from_url(r.url) or source
            ref["title"] = r.title or "Untitled"
            ref["year"] = r.year or ""
            ref["venue"] = r.venue or source
            # Store the source URL so the writer can cite it as a footnote/link.
            if r.url:
                ref["url"] = r.url

            # Collect keywords from the snippet.
            for w in (r.snippet or "").split()[:10]:
                w = w.strip(",.():;").lower()
                if len(w) > 3:
                    keywords.add(w)

            references.append(ref)

        # Build the SourceAnalysis dict.
        analyses.append(
            {
                "filename": f"Web: {topic[:60]} ({source})",
                "summary": (
                    f"Ricerca web su '{topic[:80]}' da {source}: "
                    + " ".join(summaries)[:800]
                ),
                "topics": list(dict.fromkeys(topics_list))[:10],
                "formulas": [],
                "figures": [],
                "keywords": sorted(keywords)[:20],
                "references": references,
            }
        )

    logger.info(
        "Research: %d groups → %d analyses (%d total references)",
        len(groups),
        len(analyses),
        sum(len(a["references"]) for a in analyses),
    )
    return analyses


def _domain_from_url(url: str) -> str:
    """Extract the domain name from a URL (or empty string)."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""
