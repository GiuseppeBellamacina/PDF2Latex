"""Research agent: web-based topic research that produces ``SourceAnalysis``
objects compatible with the existing analysis → plan → write pipeline.

Inspired by the STORM approach (Synthesis of Topic Outlines through Retrieval
and Multi-perspective questioning):

1. Generate diverse perspectives on the topic.
2. Generate targeted search queries from each perspective.
3. Execute searches via the configured web tool.
4. Optionally fetch full page content from top results.
5. Synthesize the gathered information into ``SourceAnalysis`` dicts.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.utils import call_llm
from app.core.config import settings
from app.core.logging import get_logger
from app.services.web_search import SearchResult, WebSearchAdapter, get_search_adapter

logger = get_logger("researcher")

PERSPECTIVE_SYSTEM = """Sei un esperto nell'esplorare argomenti da angolazioni diverse.
Ricevi un argomento e devi generare 3-5 PROSPETTIVE DIVERSE da cui esplorarlo.

Ogni prospettiva deve essere un punto di vista diverso, non una query di ricerca:
- Prospettiva storica: come si è evoluto l'argomento
- Prospettiva tecnica: i meccanismi e i dettagli di funzionamento
- Prospettiva applicativa: casi d'uso reali, esempi, implementazioni
- Prospettiva critica: limiti, controversie, sfide aperte
- Prospettiva comparativa: confronto con approcci alternativi

Scrivi in {language}.

Restituisci ESCLUSIVAMENTE un array JSON di stringhe:
["Prospettiva 1", "Prospettiva 2", "Prospettiva 3"]
Non aggiungere testo fuori dall'array."""

QUERY_GENERATION_SYSTEM = """Sei un ricercatore esperto. Ricevi un argomento e una prospettiva
specifica da cui esplorarlo. Genera query di ricerca mirate per quella prospettiva.

Genera query in {language} che coprano la prospettiva data, cercando:
- Fonti autorevoli e aggiornate
- Dati concreti, studi, paper
- Esempi specifici e casi reali

Restituisci ESCLUSIVAMENTE un array JSON di stringhe:
["query 1", "query 2"]
Non aggiungere testo fuori dall'array."""

SYNTHESIS_SYSTEM = """Sei un analista esperto. Ricevi i risultati di una ricerca web su un
argomento e devi produrre un'analisi strutturata in {language}.

Produci un'analisi che includa:
- Un riassunto di 3-5 frasi che copra i punti principali emersi dalla ricerca
- Un elenco degli argomenti principali trattati (topic)
- Le formule o concetti chiave rilevanti (in notazione LaTeX se applicabile)
- Figure, schemi o architetture menzionate nei risultati
- Parole chiave utili
- Riferimenti bibliografici REALMENTE presenti nei risultati (con autori, titolo, anno, sede)

Analizza SOLO ciò che è effettivamente presente nei risultati: non inventare
contenuti e non inventare riferimenti.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido:
{{
  "summary": "...",
  "topics": ["...", "..."],
  "formulas": ["...", "..."],
  "figures": ["...", "..."],
  "keywords": ["...", "..."],
  "references": [
    {{"authors": "Cognome1 and Cognome2", "title": "Titolo", "year": "2021", "venue": "Rivista/Conferenza"}}
  ]
}}
Non aggiungere testo prima o dopo il JSON."""


async def generate_perspectives(
    topic: str,
    language: str,
    llm_config: dict[str, Any],
    n_perspectives: int = 4,
) -> list[str]:
    """Generate diverse perspectives on a topic (STORM step 1)."""
    system = PERSPECTIVE_SYSTEM.replace("{language}", language)
    user = (
        f"Argomento: {topic}\n\n"
        f"Genera esattamente {n_perspectives} prospettive diverse "
        f"per esplorare questo argomento a fondo."
    )
    try:
        from app.agents.utils import parse_json_response

        raw = await call_llm(llm_config, system, user, label="research-persp")
        data = parse_json_response(raw)
        if isinstance(data, list) and all(isinstance(p, str) for p in data):
            return [p for p in data if p.strip()][:n_perspectives]
        lines = [
            ln.strip()
            for ln in raw.splitlines()
            if ln.strip() and not ln.startswith("[")
        ]
        if lines:
            return lines[:n_perspectives]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Perspective generation failed: %s", exc)
    return [topic]


async def generate_queries(
    topic: str,
    language: str,
    llm_config: dict[str, Any],
    perspective: str = "",
    n_queries: int | None = None,
) -> list[str]:
    """Generate search queries for the given topic from a specific perspective."""
    n = n_queries or max(1, settings.research_max_queries // 2)
    system = QUERY_GENERATION_SYSTEM.replace("{language}", language)
    persp_text = perspective or topic
    user = (
        f"Argomento: {topic}\n"
        f"Prospettiva: {persp_text}\n\n"
        f"Genera esattamente {n} query di ricerca mirate "
        f"per esplorare l'argomento da questa prospettiva."
    )
    try:
        from app.agents.utils import parse_json_response

        raw = await call_llm(llm_config, system, user, label="research-query-gen")
        data = parse_json_response(raw)
        if isinstance(data, list) and all(isinstance(q, str) for q in data):
            return [q for q in data if q.strip()][:n]
        # Fallback: treat each non-empty line as a query.
        lines = [
            ln.strip()
            for ln in raw.splitlines()
            if ln.strip() and not ln.startswith("[")
        ]
        if lines:
            return lines[:n]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query generation failed: %s", exc)
    return [topic]


async def fetch_pages_batch(
    adapter: WebSearchAdapter, urls: list[str]
) -> dict[str, str]:
    """Fetch multiple URLs in parallel, returning a {url: text} mapping."""
    sem = asyncio.Semaphore(max(1, settings.research_max_fetch_concurrency))

    async def _fetch_one(url: str) -> tuple[str, str]:
        async with sem:
            text = await adapter.fetch_page(url)
        return url, text

    tasks = [_fetch_one(u) for u in urls if u]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, str] = {}
    for r in results:
        if isinstance(r, tuple):
            out[r[0]] = r[1]
    return out


async def synthesize_analysis(
    results: list[SearchResult],
    language: str,
    llm_config: dict[str, Any],
    topic_hint: str = "",
) -> dict[str, Any]:
    """Synthesize search results into a SourceAnalysis-style dict."""
    # Build a combined text from all results.
    parts: list[str] = []
    for i, r in enumerate(results, start=1):
        parts.append(f"--- Risultato {i}: {r.title} ---")
        if r.url:
            parts.append(f"URL: {r.url}")
        parts.append(r.content or r.snippet)
        parts.append("")
    combined = "\n".join(parts)

    system = SYNTHESIS_SYSTEM.replace("{language}", language)
    user = (
        f"Argomento: {topic_hint}\n\n"
        f"RISULTATI DELLA RICERCA WEB:\n\n{combined}\n\n"
        f"Produci un'analisi strutturata basata ESCLUSIVAMENTE su questi risultati."
    )
    try:
        from app.agents.utils import parse_json_response

        raw = await call_llm(llm_config, system, user, label="research-synth")
        data = parse_json_response(raw)
        if isinstance(data, dict):
            return {
                "summary": str(data.get("summary", "")),
                "topics": [str(t) for t in (data.get("topics") or [])],
                "formulas": [str(f) for f in (data.get("formulas") or [])],
                "figures": [str(f) for f in (data.get("figures") or [])],
                "keywords": [str(k) for k in (data.get("keywords") or [])],
                "references": [
                    {
                        "authors": str(r.get("authors", "")),
                        "title": str(r.get("title", "")),
                        "year": str(r.get("year", "")),
                        "venue": str(r.get("venue", "")),
                    }
                    for r in (data.get("references") or [])
                    if isinstance(r, dict) and r.get("title")
                ],
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Synthesis failed: %s", exc)

    # Minimal fallback: return a skeleton analysis.
    return {
        "summary": f"Ricerca web su '{topic_hint}'"[:200],
        "topics": [topic_hint] if topic_hint else [],
        "formulas": [],
        "figures": [],
        "keywords": [],
        "references": [],
    }


async def research_topic(
    topic: str,
    language: str,
    llm_config: dict[str, Any],
    web_tool_configs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run the full research pipeline: perspectives → queries → search → fetch → synthesize.

    Searches EVERY assigned tool for EACH query in parallel, merging and
    deduplicating results before synthesis. This gives the LLM the broadest
    possible coverage from all configured search engines.

    Returns a list of ``SourceAnalysis``-compatible dicts, each with a
    ``filename`` key set to ``\"Web: <query>\"`` so downstream nodes can
    distinguish web-sourced analyses.
    """
    # Create all adapters from the list of configs.
    # Each config gets a reference to the full resolved list so adapters like
    # WebAgent can auto-resolve API keys for their nested search_tools.
    adapters: list[WebSearchAdapter] = []
    for config in web_tool_configs:
        config["_resolved_web_tools"] = web_tool_configs
        adapter = get_search_adapter(config)
        if adapter is not None:
            adapters.append(adapter)
        else:
            logger.warning(
                "No web search adapter available for tool_type=%s; skipping",
                config.get("tool_type"),
            )

    if not adapters:
        logger.warning("No web search adapters available; skipping research")
        return []

    tool_types = [a.tool_type for a in adapters]
    logger.info("Research: using %d adapters: %s", len(adapters), ", ".join(tool_types))

    # 1. Generate diverse perspectives (STORM step 1).
    perspectives = await generate_perspectives(topic, language, llm_config)
    logger.info(
        "Research: generated %d perspectives for topic '%s'", len(perspectives), topic
    )

    # 2. Generate search queries from each perspective (STORM step 2).
    all_queries: list[str] = []
    for persp in perspectives:
        qs = await generate_queries(topic, language, llm_config, perspective=persp)
        all_queries.extend(qs)
    queries = list(dict.fromkeys(all_queries))
    if not queries:
        queries = await generate_queries(topic, language, llm_config)
    logger.info(
        "Research: generated %d queries across %d perspectives",
        len(queries),
        len(perspectives),
    )

    # 3. Execute all queries against ALL adapters in parallel.
    #    Each query is sent to every adapter; results are merged and
    #    deduplicated by URL so the same page isn't listed twice.
    async def _search_all(q: str) -> tuple[str, list[SearchResult]]:
        tasks = [adapter.search(q) for adapter in adapters]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        merged: list[SearchResult] = []
        seen_urls: set[str] = set()
        for result in gathered:
            if isinstance(result, Exception):
                logger.warning("Search failed for query '%s': %s", q, result)
                continue
            if isinstance(result, list):
                for r in result:
                    key = r.url or r.title
                    if key and key not in seen_urls:
                        seen_urls.add(key)
                        merged.append(r)
                    elif not key:
                        merged.append(r)
        return q, merged

    search_results = await asyncio.gather(*[_search_all(q) for q in queries])
    all_results: list[tuple[str, list[SearchResult]]] = [
        (q, res) for q, res in search_results if res
    ]
    total_hits = sum(len(res) for _, res in all_results)
    logger.info(
        "Research: %d/%d queries returned results (%d total hits across %d tools)",
        len(all_results),
        len(queries),
        total_hits,
        len(adapters),
    )

    if not all_results:
        return []

    # 4. Optionally fetch full page content (use the first adapter for fetching).
    primary_adapter = adapters[0]
    if settings.research_fetch_pages:
        all_urls: list[str] = []
        for _q, results in all_results:
            for r in results:
                if r.url and not r.content:
                    all_urls.append(r.url)
        if all_urls:
            fetched = await fetch_pages_batch(
                primary_adapter, list(dict.fromkeys(all_urls))
            )
            logger.info("Research: fetched %d pages", len(fetched))
            # Merge fetched content back into results.
            for _q, results in all_results:
                for r in results:
                    if r.url in fetched and fetched[r.url]:
                        r.content = fetched[r.url]

    # 5. Synthesize each query's results into a SourceAnalysis.
    async def _synth_one(q: str, results: list[SearchResult]) -> dict[str, Any] | None:
        try:
            analysis = await synthesize_analysis(
                results, language, llm_config, topic_hint=q
            )
            analysis["filename"] = f"Web: {q[:80]}"
            return analysis
        except Exception as exc:  # noqa: BLE001
            logger.warning("Synthesis failed for query '%s': %s", q, exc)
            return None

    syntheses = await asyncio.gather(*[_synth_one(q, res) for q, res in all_results])
    analyses = [s for s in syntheses if s is not None]
    logger.info("Research: synthesized %d analyses from web results", len(analyses))
    return analyses
