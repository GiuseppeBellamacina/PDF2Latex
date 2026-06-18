"""Web Agent: agentic LangGraph flow for iterative web search.

The agent can work in two modes:

1. **Pure LLM mode** — the planner generates URLs, the fetcher downloads them,
   and the evaluator decides whether to continue.

2. **Hybrid mode** — when ``search_adapters`` are provided, they are queried
   first (Tavily, Wikipedia, Perplexity, etc.). Results with content go
   straight to ``collected_results``; URLs needing a fetch are queued as
   seed URLs so the first round skips the planner and goes directly to the
   fetcher. The LLM planner only kicks in when more digging is needed.

The loop repeats until the evaluator is satisfied or ``max_iterations`` is reached.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.utils import call_llm, call_llm_structured
from app.core.logging import get_logger
from app.services.web_search import (
    SearchResult,
    WebSearchAdapter,
    strip_html,
)

logger = get_logger("web_agent")

# --------------------------------------------------------------------------- #
# Prompts                                                                      #
# --------------------------------------------------------------------------- #

PLANNER_SYSTEM = """Sei un agente di ricerca web. Il tuo compito è generare URL precisi
da visitare per trovare informazioni su un argomento.

Regole:
- Genera URL REALI e SPECIFICI di pagine che probabilmente contengono le informazioni
  richieste (Wikipedia, documentazione ufficiale, paper accademici, articoli tecnici).
- NON generare URL inventati o inesistenti.
- Usa sottopagine specifiche, non solo la homepage (es. /wiki/Topic, /docs/feature).
- Se l'argomento riguarda un tool o una libreria, cerca la documentazione ufficiale.
- Se sono già stati visitati alcuni URL, NON ripeterli.
- Ogni URL deve essere completo (https://...).

**Strategia**: Ti verranno mostrati i contenuti già raccolti (da Wikipedia, motori di
ricerca, o dal fetch di pagine precedenti). Usali per:
- Identificare GAP: cosa MANCA ancora? Quali dettagli tecnici, esempi, o prospettive
  non sono ancora coperti?
- Cercare FONTI SPECIALIZZATE: se Wikipedia ha già coperto le basi, cerca paper
  accademici, documentazione ufficiale, o articoli tecnici approfonditi.
- Evitare RIDONDANZE: non cercare informazioni già ampiamente coperte nei risultati
  esistenti.

Genera 1-3 URL per questa iterazione. Se pensi di aver già coperto tutto,
restituisci una lista vuota."""

PLANNER_USER = """Argomento di ricerca: {query}

URL già visitati:
{visited_urls}

--- CONOSCENZA GIÀ RACCOLTA ---
{collected_context}
---

In base a quanto già raccolto, quali informazioni MANCANO ancora?
Genera 1-3 URL di fonti specializzate per colmare i gap."""


EVALUATOR_SYSTEM = """Sei un valutatore di ricerca web. Hai appena scaricato alcune pagine
web relative a un argomento. Devi:
1. Estrarre le informazioni UTILI e PERTINENTI da ogni nuova pagina.
2. Decidere se la CONOSCENZA COMPLESSIVA (nuove pagine + risultati già raccolti
   da search engine e iterazioni precedenti) è SUFFICIENTE per rispondere
   all'argomento di ricerca.

**Criteri di sufficienza**:
- L'argomento è coperto da più fonti autorevoli e complementari?
- Ci sono dettagli tecnici, esempi concreti o dati a supporto?
- Mancano ancora prospettive importanti (storica, tecnica, applicativa, critica)?
- I risultati già raccolti (mostrati sotto) coprono già ampiamente l'argomento?
  In tal caso, NON serve cercare altro: fermati.

Rispondi ESCLUSIVAMENTE con un JSON:
{{
  "snippets": [
    {{"title": "Titolo della pagina", "url": "https://...", "content": "Testo rilevante estratto..."}}
  ],
  "reasoning": "Breve spiegazione del perché hai deciso di fermarti o continuare",
  "is_satisfied": true/false,
  "suggested_next_urls": ["url1", "url2"]  // solo se is_satisfied è false
}}

Se is_satisfied è true, suggested_next_urls deve essere vuoto.
NON inventare contenuti: estrai solo ciò che è realmente presente nelle pagine."""

EVALUATOR_USER = """Argomento di ricerca: {query}

--- NUOVE PAGINE SCARICATE ---
{fetched_pages}

--- CONOSCENZA GIÀ ACCUMULATA (search engine + iterazioni precedenti) ---
{previous_results}

Considerando TUTTA la conoscenza accumulata (nuova + pregressa),
l'argomento è sufficientemente coperto? Decidi se fermarti o continuare."""


# --------------------------------------------------------------------------- #
# State                                                                        #
# --------------------------------------------------------------------------- #


class WebAgentState(TypedDict, total=False):
    """State for the iterative Web Agent LangGraph.

    Using a TypedDict (instead of bare ``dict``) ensures LangGraph applies
    per-key last-value reducers — each node's return is a partial update
    that only overwrites the keys it explicitly returns. All other keys are
    preserved from the previous state.
    """

    query: str
    llm_config: dict[str, Any]
    max_iterations: int
    iteration: int
    visited_urls: list[str]
    current_urls: list[str]
    scraped_content: dict[str, str]
    collected_results: list[SearchResult]
    is_complete: bool
    planner_reasoning: str
    evaluation_reasoning: str
    suggested_next_urls: list[str]


# --------------------------------------------------------------------------- #
# Schemas                                                                      #
# --------------------------------------------------------------------------- #


class PlannedUrls(BaseModel):
    """Output of the planner node: URLs to fetch next."""

    urls: list[str] = Field(default_factory=list, description="URLs to fetch (1-3)")
    reasoning: str = Field(default="", description="Why these URLs were chosen")


class EvaluationResult(BaseModel):
    """Output of the evaluator node."""

    snippets: list[dict[str, str]] = Field(
        default_factory=list,
        description="Useful snippets extracted from the fetched pages",
    )
    reasoning: str = Field(default="", description="Why stop or continue")
    is_satisfied: bool = Field(
        default=False,
        description="True if the query is fully answered",
    )
    suggested_next_urls: list[str] = Field(
        default_factory=list,
        description="URLs to try next (only if not satisfied)",
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


async def _fetch_url(url: str) -> tuple[str, str]:
    """Fetch a single URL and return (url, stripped_text)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "PDF2LaTeX/1.0"})
            resp.raise_for_status()
            return url, strip_html(resp.text)[:4000]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Web Agent: failed to fetch %s: %s", url, exc)
        return url, ""


# --------------------------------------------------------------------------- #
# LangGraph nodes                                                              #
# --------------------------------------------------------------------------- #


async def planner_node(state: WebAgentState) -> dict[str, Any]:
    """Generate URLs to fetch based on the query and what's already known."""
    llm_config: dict[str, Any] = state.get("llm_config") or {}
    query: str = state.get("query") or ""
    visited: list[str] = state.get("visited_urls", [])
    collected: list[SearchResult] = state.get("collected_results", [])

    visited_str = "\n".join(f"- {u}" for u in visited[-10:]) or "(nessuno)"
    # Build rich context from collected results: title + snippet for each.
    context_parts: list[str] = []
    for r in collected[-10:]:
        parts = [f"[{r.title}]({r.url})"]
        snippet = (r.snippet or r.content or "")[:300]
        if snippet.strip():
            parts.append(f"  {snippet.strip()}")
        context_parts.append("\n".join(parts))
    collected_context = "\n\n".join(context_parts) or "(nessuna conoscenza pregressa)"

    user = PLANNER_USER.format(
        query=query,
        visited_urls=visited_str,
        collected_context=collected_context,
    )

    try:
        planned = await call_llm_structured(
            llm_config,
            PLANNER_SYSTEM,
            user,
            schema=PlannedUrls,
            label="web-agent-planner",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Web Agent planner failed: %s", exc)
        # Fallback: try a plain call.
        raw = await call_llm(
            llm_config, PLANNER_SYSTEM, user, label="web-agent-planner-fallback"
        )
        planned = PlannedUrls(urls=[], reasoning=raw[:200])

    # Filter out already-visited URLs.
    visited_set = set(visited)
    new_urls = [u for u in planned.urls if u not in visited_set][:3]

    logger.info(
        "Web Agent planner: %d new URLs (reasoning: %s)",
        len(new_urls),
        planned.reasoning[:120],
    )

    return {
        "current_urls": new_urls,
        "planner_reasoning": planned.reasoning,
    }


async def fetcher_node(state: WebAgentState) -> dict[str, Any]:
    """Fetch the planned URLs in parallel and extract readable text."""
    urls: list[str] = state.get("current_urls", [])
    visited: list[str] = list(state.get("visited_urls", []))

    if not urls:
        return {
            "scraped_content": {},
            "visited_urls": visited,
            "iteration": state.get("iteration", 0) + 1,
        }

    # Fetch all URLs in parallel.
    tasks = [_fetch_url(u) for u in urls]
    results = await asyncio.gather(*tasks)

    scraped: dict[str, str] = {}
    for url, text in results:
        if text:
            scraped[url] = text

    new_visited = list(visited) + [u for u in urls if u not in visited]

    logger.info(
        "Web Agent fetcher: %d/%d pages fetched successfully",
        len(scraped),
        len(urls),
    )

    return {
        "scraped_content": scraped,
        "visited_urls": new_visited,
        "iteration": state.get("iteration", 0) + 1,
    }


async def evaluator_node(state: WebAgentState) -> dict[str, Any]:
    """Evaluate fetched content, extract snippets, and decide whether to stop."""
    llm_config: dict[str, Any] = state.get("llm_config") or {}
    query: str = state.get("query") or ""
    scraped: dict[str, str] = state.get("scraped_content", {})
    collected: list[SearchResult] = list(state.get("collected_results", []))

    # Build a summary of fetched pages.
    fetched_parts: list[str] = []
    for url, text in scraped.items():
        fetched_parts.append(f"--- {url} ---\n{text[:3000]}\n")
    fetched_str = "\n".join(fetched_parts) or "(nessuna pagina scaricata)"

    # Summary of previous results (richer format, up to 500 chars per snippet).
    prev_parts: list[str] = []
    for r in collected:
        snippet = (r.snippet or r.content or "")[:500]
        if snippet.strip():
            prev_parts.append(f"[{r.title}]({r.url}): {snippet.strip()}")
        else:
            prev_parts.append(f"[{r.title}]({r.url})")
    prev_str = "\n".join(prev_parts) or "(nessun risultato precedente)"

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
            schema=EvaluationResult,
            label="web-agent-evaluator",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Web Agent evaluator failed: %s", exc)
        evaluation = EvaluationResult(
            snippets=[],
            reasoning=str(exc)[:200],
            is_satisfied=True,  # stop on error
            suggested_next_urls=[],
        )

    # Convert snippets to SearchResult objects and add to collected.
    new_results: list[SearchResult] = []
    for s in evaluation.snippets:
        if s.get("title") and s.get("content"):
            new_results.append(
                SearchResult(
                    title=str(s.get("title", "")),
                    url=str(s.get("url", "")),
                    snippet=str(s.get("content", ""))[:500],
                    content=str(s.get("content", ""))[:8000],
                )
            )

    updated_collected = list(collected) + new_results

    logger.info(
        "Web Agent evaluator: %d new snippets, satisfied=%s (reasoning: %s)",
        len(new_results),
        evaluation.is_satisfied,
        evaluation.reasoning[:120],
    )

    return {
        "collected_results": updated_collected,
        "is_complete": evaluation.is_satisfied,
        "suggested_next_urls": (
            evaluation.suggested_next_urls if not evaluation.is_satisfied else []
        ),
        "evaluation_reasoning": evaluation.reasoning,
    }


# --------------------------------------------------------------------------- #
# Routing                                                                      #
# --------------------------------------------------------------------------- #


def _after_start(state: WebAgentState) -> str:
    """Route to fetcher if search engines gave us seed URLs; otherwise plan."""
    if state.get("current_urls"):
        logger.info(
            "Web Agent: %d seed URLs from search engines, skipping to fetcher",
            len(state["current_urls"]),
        )
        return "fetcher"
    return "planner"


def _after_evaluator(state: WebAgentState) -> str:
    """Decide whether to loop back to planner or end."""
    max_iter = state.get("max_iterations", 3)
    iteration = state.get("iteration", 0)
    is_complete = state.get("is_complete", False)

    if is_complete:
        logger.info("Web Agent: evaluator satisfied, stopping")
        return END
    if iteration >= max_iter:
        logger.info("Web Agent: max iterations (%d) reached, stopping", max_iter)
        return END

    return "planner"


# --------------------------------------------------------------------------- #
# Graph builder                                                                #
# --------------------------------------------------------------------------- #


def build_web_agent_graph() -> StateGraph:
    """Build the iterative Web Agent LangGraph."""
    graph = StateGraph(WebAgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("fetcher", fetcher_node)
    graph.add_node("evaluator", evaluator_node)

    graph.add_conditional_edges(
        START,
        _after_start,
        {"planner": "planner", "fetcher": "fetcher"},
    )
    graph.add_edge("planner", "fetcher")
    graph.add_edge("fetcher", "evaluator")

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
    """Run the Web Agent LangGraph flow and return collected search results.

    Args:
        query: The search query / topic to research.
        llm_config: LLM provider config (provider, model, api_key, base_url).
        max_iterations: Maximum number of planner→fetch→evaluate loops.
        search_adapters: Optional list of pre-configured search adapters
            (Tavily, Wikipedia, Perplexity, etc.). When provided, they are
            queried first and their results seed the agent state — URLs get
            queued for fetching, content-rich results go straight to the
            collected pool. The LLM planner only generates new URLs when
            more digging is needed.

    Returns:
        A list of ``SearchResult`` objects collected during the research.
    """
    logger.info(
        "Web Agent: starting research on '%s' (max %d iterations, %d search adapters)",
        query[:100],
        max_iterations,
        len(search_adapters) if search_adapters else 0,
    )

    # ── Phase 0: query all configured search engines for seed URLs ───────
    visited: list[str] = []
    current_urls: list[str] = []
    collected: list[SearchResult] = []

    if search_adapters:
        tasks = [a.search(query) for a in search_adapters]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        seen_urls: set[str] = set()
        for result in gathered:
            if isinstance(result, Exception):
                logger.warning("Web Agent: search adapter failed: %s", result)
                continue
            if isinstance(result, list):
                for r in result:
                    if r.content:
                        # Content-rich result: add directly to collected.
                        collected.append(r)
                    if r.url:
                        key = r.url.strip().lower()
                        if key and key not in seen_urls:
                            seen_urls.add(key)
                            if not r.content:
                                # URL-only result: queue for fetching.
                                current_urls.append(r.url)
                            visited.append(r.url)

        logger.info(
            "Web Agent: %d seed results from search engines "
            "(%d with content, %d URLs to fetch)",
            len(visited),
            len(collected),
            len(current_urls),
        )

    initial: dict[str, Any] = {
        "query": query,
        "llm_config": llm_config,
        "max_iterations": max(max_iterations, 1),
        "iteration": 0,
        "visited_urls": visited,
        "current_urls": current_urls,
        "scraped_content": {},
        "collected_results": collected,
        "is_complete": False,
        "planner_reasoning": "",
        "evaluation_reasoning": "",
        "suggested_next_urls": [],
    }

    graph = build_web_agent_graph()
    final = await graph.ainvoke(initial)

    results: list[SearchResult] = final.get("collected_results", []) or []
    logger.info(
        "Web Agent: finished with %d results after %d iterations",
        len(results),
        final.get("iteration", 0),
    )
    return results
