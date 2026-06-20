"""Web Agent: multi-node agentic LangGraph for iterative web research.

The agent is composed of SEPARATE specialized nodes, each responsible for one
search source. They fan out in parallel, then a deduplicator removes redundant
results before a merger consolidates everything. An evaluator decides whether
sufficient information has been gathered or another pass is needed.

Graph topology::

    planner → fan_out ─┬─ tavily_search
                       ├─ perplexity_search
                       ├─ wikipedia_search
                       ├─ arxiv_search
                       └─ custom_urls_search
                              │
                              ▼
    deduplicator ←───────── fan-in (operator.add)
         │
         ▼
    merger (fetch full pages, chunk)
         │
         ▼
    evaluator → [planner or END]

Multi-pass: the evaluator identifies gaps and generates refined queries; the
planner uses them to feed the specialised nodes again.

Output: ``collected_results`` carries ``SearchResult`` objects with citation
metadata (authors, year, venue). The caller maps them to ``SourceAnalysis``
dicts so the downstream pipeline treats web research like any other source.
"""

from __future__ import annotations

import asyncio
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.utils import call_llm, call_llm_structured
from app.core.logging import get_logger
from app.services.web_search import (
    USER_AGENT,
    SearchResult,
    WebSearchAdapter,
    strip_html,
)

logger = get_logger("web_agent")

# --------------------------------------------------------------------------- #
# Prompts                                                                      #
# --------------------------------------------------------------------------- #

PLANNER_SYSTEM = """Sei un agente di ricerca web. Il tuo compito è generare query di ricerca
mirate e URL precisi per trovare informazioni su un argomento.

**Strategia**: Ti verranno mostrati i contenuti già raccolti. Usali per:
- Identificare GAP: cosa MANCA ancora? Quali dettagli tecnici, esempi, o prospettive
  non sono ancora coperti?
- Cercare FONTI SPECIALIZZATE: se le basi sono coperte, cerca paper accademici,
  documentazione ufficiale, o articoli tecnici approfonditi.
- Evitare RIDONDANZE: non cercare informazioni già ampiamente coperte.

Genera query per TUTTI i motori di ricerca configurati e 1-3 URL diretti da visitare.
Se pensi di aver già coperto tutto, restituisci liste vuote."""

PLANNER_USER = """Argomento di ricerca: {query}

--- CONOSCENZA GIÀ RACCOLTA ---
{collected_context}
---

Tool configurati: {configured_tools}

In base a quanto già raccolto, quali informazioni MANCANO ancora?
Genera query per ogni tool e 1-3 URL diretti di fonti specializzate."""


EVALUATOR_SYSTEM = """Sei un valutatore di ricerca web. Hai appena raccolto e scaricato
informazioni relative a un argomento. Devi:

1. Estrarre le informazioni UTILI e PERTINENTI da ogni nuova pagina.
2. Decidere se la CONOSCENZA COMPLESSIVA è SUFFICIENTE per rispondere
   all'argomento di ricerca.

**Criteri di sufficienza**:
- L'argomento è coperto da più fonti autorevoli e complementari?
- Ci sono dettagli tecnici, esempi concreti o dati a supporto?
- Mancano ancora prospettive importanti?

Rispondi ESCLUSIVAMENTE con un JSON."""

EVALUATOR_USER = """Argomento di ricerca: {query}

--- NUOVE PAGINE SCARICATE ---
{fetched_pages}

--- CONOSCENZA GIÀ ACCUMULATA ---
{previous_results}

Considerando TUTTA la conoscenza accumulata, l'argomento è sufficientemente coperto?"""


# --------------------------------------------------------------------------- #
# State and schemas                                                           #
# --------------------------------------------------------------------------- #


class PlannedQueries(BaseModel):
    """Output of the planner: queries per tool + custom URLs."""

    queries: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Per-tool search queries, e.g. {'tavily': ['q1'], 'arxiv': ['deep learning survey']}",
    )
    custom_urls: list[str] = Field(
        default_factory=list,
        description="Direct URLs to fetch (1-3)",
    )
    reasoning: str = Field(default="", description="Why these were chosen")


class EvalResult(BaseModel):
    """Output of the evaluator node."""

    snippets: list[dict[str, str]] = Field(
        default_factory=list,
        description="Useful info extracted from fetched pages",
    )
    reasoning: str = Field(default="", description="Why stop or continue")
    is_satisfied: bool = Field(
        default=False, description="True if the query is fully answered"
    )
    refined_queries: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Refined queries for next pass (only if not satisfied)",
    )
    refined_urls: list[str] = Field(
        default_factory=list,
        description="More URLs to try (only if not satisfied)",
    )


class WebAgentState(TypedDict, total=False):
    """Multi-node agent state.

    ``new_results`` uses ``operator.add`` so parallel search nodes can
    append concurrently without race conditions.
    """

    query: str
    llm_config: dict[str, Any]
    max_iterations: int
    iteration: int
    # Per-tool queries (planner output → fan-out input).
    per_tool_queries: dict[str, list[str]]
    custom_urls: list[str]
    # Fan-in: parallel nodes append via operator.add.
    new_results: Annotated[list[SearchResult], operator.add]
    # Deduplicated + merged results for this pass.
    deduped_results: list[SearchResult]
    # Fetched page content keyed by URL.
    scraped_content: dict[str, str]
    # Running accumulated results across all passes.
    collected_results: list[SearchResult]
    # Tracking.
    visited_urls: list[str]
    is_complete: bool
    planner_reasoning: str
    evaluation_reasoning: str


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


async def _fetch_url(url: str) -> tuple[str, str]:
    """Fetch a single URL and return (url, stripped_text)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return url, strip_html(resp.text)[:4000]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Web Agent: failed to fetch %s: %s", url, exc)
        return url, ""


# --------------------------------------------------------------------------- #
# LangGraph nodes                                                              #
# --------------------------------------------------------------------------- #


async def planner_node(state: WebAgentState) -> dict[str, Any]:
    """Generate per-tool queries and custom URLs for this pass."""
    llm_config: dict[str, Any] = state.get("llm_config") or {}
    query: str = state.get("query") or ""
    collected: list[SearchResult] = state.get("collected_results", [])

    # Build context from previously collected results.
    context_parts: list[str] = []
    for r in collected[-15:]:
        descr = f"[{r.title}]"
        if r.url:
            descr += f"({r.url})"
        snippet = (r.snippet or r.content or "")[:300]
        if snippet.strip():
            descr += f": {snippet.strip()}"
        context_parts.append(descr)
    collected_context = "\n".join(context_parts) or "(nessuna conoscenza pregressa)"

    user = PLANNER_USER.format(
        query=query,
        collected_context=collected_context,
        configured_tools="tavily, perplexity, wikipedia, arxiv, custom_urls",
    )

    try:
        planned = await call_llm_structured(
            llm_config,
            PLANNER_SYSTEM,
            user,
            schema=PlannedQueries,
            label="web-agent-planner",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Web Agent planner failed: %s", exc)
        raw = await call_llm(
            llm_config, PLANNER_SYSTEM, user, label="web-agent-planner-fallback"
        )
        planned = PlannedQueries(
            queries={"tavily": [query], "wikipedia": [query]},
            custom_urls=[],
            reasoning=raw[:200],
        )

    logger.info(
        "Web Agent planner: tools=%s, custom_urls=%d (reasoning: %s)",
        list(planned.queries.keys()),
        len(planned.custom_urls),
        planned.reasoning[:120],
    )

    return {
        "per_tool_queries": planned.queries,
        "custom_urls": planned.custom_urls,
        "planner_reasoning": planned.reasoning,
        "new_results": [],  # reset accumulator
        "scraped_content": {},
    }


# ── Specialised search nodes (run in parallel after planner) ────────────────


def _make_search_node(
    tool_type: str,
    search_fn,
) -> callable:
    """Factory: create a search node for one tool type.

    Each node reads ``per_tool_queries[tool_type]``, searches each query,
    and appends results to ``new_results`` (fan-in via ``operator.add``).
    """

    async def _node(state: WebAgentState) -> dict[str, Any]:
        per_tool: dict[str, list[str]] = state.get("per_tool_queries", {}) or {}
        queries = per_tool.get(tool_type, [])
        if not queries:
            return {"new_results": []}

        results: list[SearchResult] = []
        for q in queries:
            try:
                batch = await search_fn(q)
                if isinstance(batch, list):
                    results.extend(batch)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Web Agent: %s search failed for '%s': %s",
                    tool_type,
                    q[:80],
                    exc,
                )

        logger.info(
            "Web Agent: %s node → %d results from %d queries",
            tool_type,
            len(results),
            len(queries),
        )
        return {"new_results": list(results)}

    _node.__name__ = f"{tool_type}_search_node"
    return _node


async def custom_urls_node(state: WebAgentState) -> dict[str, Any]:
    """Fetch the LLM-planned custom URLs and extract content."""
    urls: list[str] = state.get("custom_urls", [])
    visited: list[str] = state.get("visited_urls", [])
    visited_set = set(visited)

    new_urls = [u for u in urls if u.strip() and u.strip().lower() not in visited_set]
    if not new_urls:
        return {"new_results": []}

    tasks = [_fetch_url(u) for u in new_urls]
    fetched = await asyncio.gather(*tasks)

    results: list[SearchResult] = []
    scraped: dict[str, str] = {}
    for url, text in fetched:
        if text:
            scraped[url] = text
            results.append(
                SearchResult(
                    title=url.split("/")[-1] or url,
                    url=url,
                    snippet=text[:500],
                    content=text[:8000],
                    venue=url.split("/")[2] if url.startswith("http") else "",
                )
            )

    logger.info(
        "Web Agent: custom_urls → %d fetched, %d new results",
        len(scraped),
        len(results),
    )
    return {"new_results": results, "scraped_content": scraped}


async def deduplicator_node(state: WebAgentState) -> dict[str, Any]:
    """Deduplicate new_results by URL (normalised), merging content.

    When the same URL appears in multiple results (across tools or passes),
    the one with richer content is kept. URLs already in ``visited_urls``
    are dropped.
    """
    new_results: list[SearchResult] = state.get("new_results", []) or []
    visited: list[str] = state.get("visited_urls", [])
    visited_set = {u.strip().lower() for u in visited}

    # Allow multiple results with NO URL (e.g. Perplexity answer blocks).
    no_url_results: list[SearchResult] = []
    seen: dict[str, SearchResult] = {}

    for r in new_results:
        key = (r.url or "").strip().lower()
        if not key:
            no_url_results.append(r)
            continue
        if key in visited_set:
            continue
        existing = seen.get(key)
        if existing is None or len(r.content) > len(existing.content):
            seen[key] = r

    deduped = no_url_results + list(seen.values())

    dropped = len(new_results) - len(deduped)
    if dropped:
        logger.info(
            "Web Agent dedup: %d → %d results (%d duplicates dropped)",
            len(new_results),
            len(deduped),
            dropped,
        )

    new_visited = visited + [r.url for r in deduped if r.url]
    return {"deduped_results": deduped, "visited_urls": new_visited}


async def merger_node(state: WebAgentState) -> dict[str, Any]:
    """Merge deduped results: fetch full pages for URL-only results, then
    combine with scraped content from custom_urls.

    Non-URL results (Perplexity answers, Arxiv summaries) pass through unchanged.
    """
    deduped: list[SearchResult] = state.get("deduped_results", []) or []
    scraped: dict[str, str] = state.get("scraped_content", {}) or {}
    collected: list[SearchResult] = list(state.get("collected_results", []))

    # Identify URL-only results that need fetching (no content yet).
    to_fetch: list[str] = []
    for r in deduped:
        if r.url and not r.content and r.url not in scraped:
            to_fetch.append(r.url)

    if to_fetch:
        logger.info("Web Agent merger: fetching %d pages", len(to_fetch))
        tasks = [_fetch_url(u) for u in to_fetch]
        fetched = await asyncio.gather(*tasks)
        for url, text in fetched:
            if text:
                scraped[url] = text

    # Inject fetched content into results.
    for r in deduped:
        if r.url and not r.content and r.url in scraped:
            r.content = scraped[r.url][:8000]
        if not r.snippet and r.content:
            r.snippet = r.content[:500]

    merged = list(collected) + list(deduped)

    logger.info(
        "Web Agent merger: %d existing + %d new = %d total",
        len(collected),
        len(deduped),
        len(merged),
    )
    return {
        "collected_results": merged,
        "deduped_results": [],  # consumed
    }


async def evaluator_node(state: WebAgentState) -> dict[str, Any]:
    """Evaluate gathered knowledge, extract key info, decide whether to stop."""
    llm_config: dict[str, Any] = state.get("llm_config") or {}
    query: str = state.get("query") or ""
    collected: list[SearchResult] = state.get("collected_results", [])
    scraped: dict[str, str] = state.get("scraped_content", {}) or {}

    # Build summary of newly fetched pages (this pass).
    fetched_parts: list[str] = []
    for url, text in scraped.items():
        fetched_parts.append(f"--- {url} ---\n{text[:2000]}\n")
    fetched_str = "\n".join(fetched_parts) or "(nessuna nuova pagina)"

    # Summary of all collected results.
    prev_parts: list[str] = []
    for r in collected[-20:]:
        parts = [f"[{r.title}]({r.url})"]
        if r.authors:
            parts.append(f"  Authors: {r.authors}")
        if r.year:
            parts.append(f"  Year: {r.year}")
        if r.venue:
            parts.append(f"  Venue: {r.venue}")
        body = (r.content or r.snippet or "")[:400]
        if body.strip():
            parts.append(f"  {body.strip()}")
        prev_parts.append("\n".join(parts))
    prev_str = "\n\n".join(prev_parts) or "(nessun risultato)"

    user = EVALUATOR_USER.format(
        query=query,
        fetched_pages=fetched_str,
        previous_results=prev_str,
    )

    try:
        evaluation = await call_llm_structured(
            llm_config,
            EVALUATOR_SYSTEM,
            user,
            schema=EvalResult,
            label="web-agent-evaluator",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Web Agent evaluator failed: %s", exc)
        evaluation = EvalResult(
            snippets=[],
            reasoning=str(exc)[:200],
            is_satisfied=True,
            refined_queries={},
            refined_urls=[],
        )

    # Add evaluator-extracted snippets as enriched SearchResults.
    extra: list[SearchResult] = []
    for s in evaluation.snippets:
        if s.get("content") and s.get("title"):
            extra.append(
                SearchResult(
                    title=str(s.get("title", "")),
                    url=str(s.get("url", "")),
                    snippet=str(s.get("content", ""))[:500],
                    content=str(s.get("content", ""))[:8000],
                    venue=str(s.get("url", "")),
                )
            )

    all_collected = list(collected) + extra

    logger.info(
        "Web Agent evaluator: satisfied=%s, reasoning=%s",
        evaluation.is_satisfied,
        evaluation.reasoning[:120],
    )

    next_iteration = state.get("iteration", 0) + 1
    return {
        "collected_results": all_collected,
        "is_complete": evaluation.is_satisfied,
        "iteration": next_iteration,
        "evaluation_reasoning": evaluation.reasoning,
        # Carry refined queries + URLs for next pass (if not satisfied).
        "per_tool_queries": evaluation.refined_queries
        if not evaluation.is_satisfied
        else {},
        "custom_urls": evaluation.refined_urls if not evaluation.is_satisfied else [],
    }


# --------------------------------------------------------------------------- #
# Routing                                                                      #
# --------------------------------------------------------------------------- #


def _fan_out_to_search(
    state: WebAgentState, valid_nodes: set[str] | None = None
) -> list[str]:
    """Return the list of specialised search nodes to execute in parallel.

    Only routes to nodes that actually exist in the graph (``valid_nodes``)
    and have queries planned for them. Falls back to ``deduplicator`` when
    nothing needs searching.
    """
    if valid_nodes is None:
        valid_nodes = {"wikipedia", "arxiv", "tavily", "perplexity", "custom_urls"}

    per_tool: dict[str, list[str]] = state.get("per_tool_queries", {}) or {}
    routes: list[str] = []

    # Route to any tool node that (a) exists in the graph and (b) has queries.
    for tool in ("wikipedia", "arxiv", "tavily", "perplexity"):
        if tool in valid_nodes and per_tool.get(tool):
            routes.append(tool)

    # Custom URLs always runs if URLs were planned and the node exists.
    if "custom_urls" in valid_nodes and state.get("custom_urls"):
        routes.append("custom_urls")

    # Fallback: if nothing to do, route to deduplicator directly.
    if not routes:
        return ["deduplicator"]

    logger.info("Web Agent fan-out: %s", routes)
    return routes


def _after_start(state: WebAgentState) -> str:
    """Route START → planner directly (always start with planning)."""
    return "planner"


def _after_evaluator(state: WebAgentState) -> str:
    """Loop back to planner if not satisfied and iterations remain."""
    max_iter = state.get("max_iterations", 3)
    iteration = state.get("iteration", 0)
    is_complete = state.get("is_complete", False)

    if is_complete:
        logger.info("Web Agent: satisfied after %d iterations", iteration)
        return END
    if iteration >= max_iter:
        logger.info("Web Agent: max iterations (%d) reached", max_iter)
        return END

    return "planner"


# --------------------------------------------------------------------------- #
# Graph builder                                                                #
# --------------------------------------------------------------------------- #


def _build_search_adapters(
    params: dict[str, Any],
    resolved_tools: list[dict[str, Any]],
) -> dict[str, WebSearchAdapter]:
    """Build a lookup of adapters keyed by tool_type."""
    from app.services.web_search import get_search_adapter

    adapters: dict[str, WebSearchAdapter] = {}
    for tool_cfg in resolved_tools:
        adapter = get_search_adapter(tool_cfg)
        if adapter is not None:
            adapters[adapter.tool_type] = adapter
    return adapters


def build_web_agent_graph(
    search_adapters: list[WebSearchAdapter] | None = None,
) -> StateGraph:
    """Build the multi-node Web Agent LangGraph.

    Specialised search nodes are only added for adapters that were actually
    configured and passed in. The graph is self-contained: the caller
    provides a list of adapters (Tavily, Wikipedia, Perplexity, Arxiv, etc.)
    and the graph wires them as parallel fan-out nodes.

    Args:
        search_adapters: Pre-configured search adapters. When None or empty,
            only ``custom_urls`` (LLM-generated URLs) and ``wikipedia``
            (built-in free adapter) are available.
    """
    graph = StateGraph(WebAgentState)

    # Core nodes.
    graph.add_node("planner", planner_node)
    graph.add_node("deduplicator", deduplicator_node)
    graph.add_node("merger", merger_node)
    graph.add_node("evaluator", evaluator_node)

    # Specialised search nodes.
    search_node_names: list[str] = []

    added_tools: set[str] = set()

    if search_adapters:
        for adapter in search_adapters:
            node_name = adapter.tool_type

            # Skip web_agent itself (would be recursive).
            if node_name == "web_agent":
                continue

            async def _searcher(
                q: str, _adapter: WebSearchAdapter = adapter
            ) -> list[SearchResult]:
                return await _adapter.search(q)

            graph.add_node(node_name, _make_search_node(node_name, _searcher))
            search_node_names.append(node_name)
            added_tools.add(node_name)

    # Always add free/always-available tools (Wikipedia, Arxiv) if not already
    # added via custom adapters. The planner may generate queries for them even
    # when they weren't explicitly configured, so they must be routable.
    from app.services.web_search import ArxivAdapter, WikipediaAdapter

    if "wikipedia" not in added_tools:
        wp = WikipediaAdapter(
            {"tool_type": "wikipedia", "api_key": "", "base_url": "", "params": {}}
        )

        async def _wp_search(q):
            return await wp.search(q)

        graph.add_node("wikipedia", _make_search_node("wikipedia", _wp_search))
        search_node_names.append("wikipedia")

    if "arxiv" not in added_tools:
        arxiv_adapter = ArxivAdapter(
            {"tool_type": "arxiv", "api_key": "", "base_url": "", "params": {}}
        )

        async def _arxiv_search(q):
            return await arxiv_adapter.search(q)

        graph.add_node("arxiv", _make_search_node("arxiv", _arxiv_search))
        search_node_names.append("arxiv")

    # Custom URLs node (always present).
    graph.add_node("custom_urls", custom_urls_node)
    search_node_names.append("custom_urls")

    # ── Edges ──────────────────────────────────────────────────────────
    graph.add_edge(START, "planner")

    # Planner → fan-out to specialised nodes.
    # Build a route map from the nodes that actually exist in the graph,
    # and pass them as valid_nodes so the fan-out never routes to a missing node.
    all_search_routes = list(dict.fromkeys(search_node_names))
    valid_node_set = set(all_search_routes)
    route_map = {name: name for name in all_search_routes}
    route_map["deduplicator"] = "deduplicator"  # fallback when no queries

    # Create a closure that captures valid_node_set so _fan_out_to_search
    # only routes to nodes that were actually added to the graph.
    def _route_planner(state: WebAgentState) -> list[str]:
        return _fan_out_to_search(state, valid_node_set)

    graph.add_conditional_edges(
        "planner",
        _route_planner,
        route_map,
    )

    # Every search node → deduplicator (fan-in).
    for name in all_search_routes:
        graph.add_edge(name, "deduplicator")

    graph.add_edge("deduplicator", "merger")
    graph.add_edge("merger", "evaluator")

    graph.add_conditional_edges(
        "evaluator",
        _after_evaluator,
        {"planner": "planner", END: END},
    )

    return graph.compile()


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


async def run_web_agent(
    query: str,
    llm_config: dict[str, Any],
    max_iterations: int = 3,
    search_adapters: list[WebSearchAdapter] | None = None,
) -> list[SearchResult]:
    """Run the multi-node Web Agent LangGraph and return collected results.

    Args:
        query: The search query / topic to research.
        llm_config: LLM provider config (provider, model, api_key, base_url).
        max_iterations: Maximum number of planner→search→dedup→merge→evaluate loops.
        search_adapters: Pre-configured adapters for Tavily, Perplexity,
            Wikipedia, Arxiv, etc. When provided, each becomes a parallel
            fan-out node in the graph. Adapters with missing API keys are
            logged but do not block the graph.

    Returns:
        Collected ``SearchResult`` objects with citation metadata where available.
    """
    logger.info(
        "Web Agent: starting multi-node research on '%s' (max %d iterations, %d adapters)",
        query[:100],
        max_iterations,
        len(search_adapters) if search_adapters else 0,
    )

    initial: dict[str, Any] = {
        "query": query,
        "llm_config": llm_config,
        "max_iterations": max(max_iterations, 1),
        "iteration": 0,
        "per_tool_queries": {},
        "custom_urls": [],
        "new_results": [],
        "deduped_results": [],
        "scraped_content": {},
        "collected_results": [],
        "visited_urls": [],
        "is_complete": False,
        "planner_reasoning": "",
        "evaluation_reasoning": "",
    }

    graph = build_web_agent_graph(search_adapters)
    final = await graph.ainvoke(initial)

    results: list[SearchResult] = final.get("collected_results", []) or []
    logger.info(
        "Web Agent: finished with %d results after %d iterations",
        len(results),
        final.get("iteration", 0),
    )
    return results
