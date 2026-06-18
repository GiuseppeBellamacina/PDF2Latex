"""LangGraph orchestration: analyze -> plan -> write -> review -> assemble.

The graph fans out analysis (per document) and writing (per section) using
``asyncio.gather`` for parallelism, while keeping linear stages between them.
A progress callback is invoked at every stage so the API can stream updates
over WebSocket.

When ``research_mode`` is enabled, a ``research`` node runs in parallel with
(or instead of) ``analyze``, producing web-sourced analyses that are merged
before planning.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from app.agents.analyzer import analyze_document
from app.agents.citation_auditor import audit_citations
from app.agents.coherence import check_coherence
from app.agents.judge import judge_structure, revise_structure
from app.agents.planner import plan_document
from app.agents.prompts import OVERVIEW_SYSTEM
from app.agents.reviewer import review_document
from app.agents.schemas import OverviewSchema
from app.agents.state import GraphState
from app.agents.utils import call_llm_structured, compile_error_excerpt, tokens
from app.agents.writer import (
    expand_section,
    figure_latex,
    summarize_section_context,
    write_section,
)
from app.core.logging import get_logger
from app.services.bibliography import (
    build_bib,
    cited_keys,
    consolidate_references,
    strip_inline_bibliography,
)
from app.services.latex import (
    _escape,
    assemble_document,
    inject_bibliography,
    write_and_compile,
)
from app.services.latex_lint import lint_latex

logger = get_logger("pipeline")

MAX_REVIEW_RETRIES = 2

_FIGURE_BLOCK_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.DOTALL)
_INCLUDE_PATH_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")


def _assign_mandatory_to_sections(
    plan: list[Any], mandatory_by_name: dict[str, list[str]]
) -> list[list[str]]:
    """Give each mandatory figure to exactly ONE section.

    For every source, the sections that actually use it receive its mandatory
    figures round-robin, so a slide deck's figures are spread out instead of all
    being forced into every section that references the source (the cause of the
    same image repeating many times). Figures whose source no section uses fall
    back to the first section. Returns a per-section list aligned with ``plan``.
    """
    assigned: list[list[str]] = [[] for _ in plan]
    if not plan:
        return assigned
    for fname, figs in mandatory_by_name.items():
        target_sections = [
            i for i, s in enumerate(plan) if fname in s.get("source_filenames", [])
        ] or [0]
        for k, rel in enumerate(dict.fromkeys(figs)):
            assigned[target_sections[k % len(target_sections)]].append(rel)
    return assigned


def _dedup_figure_blocks(parts: list[str]) -> list[str]:
    """Remove repeated figure environments that point to the same image.

    The first occurrence of each image path (in document order) is kept; later
    duplicates — whether forced as mandatory or chosen by the model in several
    sections — are dropped so no figure appears twice in the document.
    """
    seen: set[str] = set()

    def _clean(part: str) -> str:
        def _sub(match: re.Match) -> str:
            block = match.group(0)
            paths = _INCLUDE_PATH_RE.findall(block)
            key = Path(paths[0]).name.lower() if paths else block
            if key in seen:
                return ""
            seen.add(key)
            return block

        return _FIGURE_BLOCK_RE.sub(_sub, part)

    return [_clean(p) for p in parts]


async def _emit(state: GraphState, event: dict[str, Any]) -> None:
    # Mirror every progress event into the server log so the backend console
    # and the UI tell the same story.
    level = event.get("level", "info")
    msg = f"[{event.get('stage', '?')}] {event.get('message', '')}"
    log = getattr(logger, level if level in ("info", "warning", "error") else "info")
    log(msg)
    cb = state.get("progress")
    if cb is not None:
        await cb(event)


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #
def _get_config(state: GraphState, role: str) -> dict[str, Any]:
    """Return the per-role LLM config if explicitly assigned, else the default."""
    role_configs: dict[str, Any] = state.get("role_configs") or {}  # type: ignore[assignment]
    return role_configs.get(role, state["llm_config"])


# --------------------------------------------------------------------------- #
# Nodes                                                                         #
# --------------------------------------------------------------------------- #
async def analyze_node(state: GraphState) -> dict[str, Any]:
    documents = state["documents"]
    llm_config = _get_config(state, "analyzer")
    await _emit(
        state,
        {
            "stage": "analyzing",
            "node": "analyze",
            "message": f"Analisi di {len(documents)} documenti",
            "progress": 5,
            "detail": ", ".join(d["filename"] for d in documents)[:200],
            "action": "docs_planned",
            "documents": [d["filename"] for d in documents],
        },
    )

    tasks = [analyze_document(doc, llm_config) for doc in documents]
    analyses = await asyncio.gather(*tasks)

    n_topics = sum(len(a["topics"]) for a in analyses)
    await _emit(
        state,
        {
            "stage": "analyzing",
            "node": "analyze",
            "message": f"Analizzati {len(analyses)} documenti",
            "progress": 25,
            "level": "success",
            "detail": f"{n_topics} argomenti individuati",
        },
    )
    return {"doc_analyses": list(analyses)}


async def research_node(state: GraphState) -> dict[str, Any]:
    """Web research node: searches the web and synthesises analyses.

    When the user provides a topic via ``user_prompt`` and enables research
    mode, this node searches the web, fetches relevant pages, and synthesizes
    results into ``SourceAnalysis`` dicts — the same format the PDF analyzer
    produces, so the rest of the pipeline is unchanged.
    """
    topic = state.get("user_prompt", "") or state.get("title", "Documento")
    if not topic.strip():
        logger.warning("Research mode enabled but no topic provided")
        return {"web_analyses": []}

    language = state.get("language", "italian")
    llm_config = _get_config(state, "researcher")
    web_tool_configs: list[dict[str, Any]] = state.get("web_tool_configs") or []

    tool_types = [c.get("tool_type", "?") for c in web_tool_configs]
    await _emit(
        state,
        {
            "stage": "researching",
            "node": "research",
            "message": f"Ricerca web: '{topic[:100]}'",
            "progress": 3,
            "detail": f"tools: {', '.join(tool_types) if tool_types else 'wikipedia'}",
        },
    )

    from app.agents.researcher import research_topic

    analyses = await research_topic(
        topic=topic,
        language=language,
        llm_config=llm_config,
        web_tool_configs=web_tool_configs,
    )

    if not analyses:
        await _emit(
            state,
            {
                "stage": "researching",
                "node": "research",
                "message": "Nessun risultato dalla ricerca web",
                "progress": 20,
                "level": "warning",
            },
        )
    else:
        n_topics = sum(len(a.get("topics", [])) for a in analyses)
        await _emit(
            state,
            {
                "stage": "researching",
                "node": "research",
                "message": f"Ricerca completata: {len(analyses)} approfondimenti",
                "progress": 20,
                "level": "success",
                "detail": f"{n_topics} argomenti individuati dalla ricerca web",
            },
        )

    return {"web_analyses": list(analyses)}


async def merge_analyses_node(state: GraphState) -> dict[str, Any]:
    """Fan-in point: merges PDF-based and web-based analyses before planning."""
    doc_analyses = state.get("doc_analyses", []) or []
    web_analyses = state.get("web_analyses", []) or []
    merged = list(doc_analyses) + list(web_analyses)

    parts: list[str] = []
    if doc_analyses:
        parts.append(f"{len(doc_analyses)} da PDF")
    if web_analyses:
        parts.append(f"{len(web_analyses)} da web")

    await _emit(
        state,
        {
            "stage": "merge",
            "node": "merge_analyses",
            "message": f"Fonti combinate: {', '.join(parts)}",
            "progress": 28,
            "level": "success",
            "detail": f"{len(merged)} analisi totali per la pianificazione",
        },
    )
    return {"analyses": merged}


async def plan_node(state: GraphState) -> dict[str, Any]:
    await _emit(
        state,
        {
            "stage": "planning",
            "node": "plan",
            "message": "Pianificazione struttura",
            "progress": 30,
        },
    )

    title, plan = await plan_document(
        analyses=[dict(a) for a in state["analyses"]],
        user_prompt=state.get("user_prompt", ""),
        language=state.get("language", "italian"),
        llm_config=_get_config(state, "planner"),
        structure_hint=state.get("structure_hint", ""),
    )

    # Prefer the user-provided document title if present.
    meta_title = (state.get("metadata") or {}).get("title")
    if meta_title:
        title = meta_title

    await _emit(
        state,
        {
            "stage": "planning",
            "node": "plan",
            "message": f"Struttura: {len(plan)} sezioni",
            "progress": 40,
            "level": "success",
            "plan": [
                {"part_title": s["part_title"], "title": s["title"]} for s in plan
            ],
        },
    )
    return {"title": title, "plan": plan}


async def write_node(state: GraphState) -> dict[str, Any]:
    plan = state["plan"]
    documents_by_name = {
        d["filename"]: d.get("full_text", "") for d in state["documents"]
    }
    mandatory_by_name = {
        d["filename"]: d.get("mandatory_figures", []) for d in state["documents"]
    }
    # Real captions extracted from the source PDFs, keyed by figure path. These
    # are bound to the figures so captions can never be swapped or mismatched.
    captions_by_path: dict[str, str] = {}
    for d in state["documents"]:
        for rel, cap in (d.get("figure_captions") or {}).items():
            if cap:
                captions_by_path[rel] = cap
    # Consolidate the references extracted from every source into one pool with
    # stable citation keys; each section is offered only the references coming
    # from its own sources, so it can \cite the ones it actually relies on.
    pool = consolidate_references(
        [(a["filename"], a.get("references", [])) for a in state.get("analyses", [])]
    )
    refs_by_source: dict[str, list[dict[str, str]]] = {}
    for ref in pool:
        refs_by_source.setdefault(ref["source_filename"], []).append(ref)
    # Assign each user-selected figure to exactly one section (round-robin across
    # the sections that use its source). Only these figures may appear; nothing
    # else is offered to the writer.
    assigned_mandatory = _assign_mandatory_to_sections(plan, mandatory_by_name)

    # ── Inject user-uploaded figures into the sections they target ──────
    user_figure_placements: dict[str, list[tuple[str, str]]] = (
        state.get("user_figure_placements") or {}
    )
    # Collect all user-uploaded figure paths for fallback tracking.
    all_user_paths: set[str] = set()
    if user_figure_placements:
        for idx, section in enumerate(plan):
            section_title = section.get("title", "")
            part_title = section.get("part_title", "")
            full_title = (
                f"{part_title} — {section_title}" if part_title else section_title
            )
            # Match by title or part_title — title combination
            matched: list[str] = []
            for target, figs in user_figure_placements.items():
                target_lower = target.lower().strip()
                if not target_lower:
                    continue  # empty target -> handle in fallback
                if (
                    target_lower == section_title.lower().strip()
                    or target_lower == full_title.lower().strip()
                    or (part_title and target_lower == part_title.lower().strip())
                ):
                    for rel_path, cap in figs:
                        matched.append(rel_path)
                        all_user_paths.add(rel_path)
                        if cap:
                            captions_by_path[rel_path] = cap
            # Add to assigned mandatory for this section
            for rel in matched:
                if rel not in assigned_mandatory[idx]:
                    assigned_mandatory[idx].append(rel)

        # ── Fallback: collect EVERY user figure (including those with
        # empty targets) and append unmatched ones to the first section ──
        all_user_figs: list[str] = []
        for figs in user_figure_placements.values():
            for rel_path, capt in figs:
                all_user_figs.append(rel_path)
                if capt:
                    captions_by_path.setdefault(rel_path, capt)
        unmatched = [r for r in dict.fromkeys(all_user_figs) if r not in all_user_paths]
        if unmatched and plan:
            for rel in unmatched:
                if rel not in assigned_mandatory[0]:
                    assigned_mandatory[0].append(rel)
            await _emit(
                state,
                {
                    "stage": "writing",
                    "node": "write",
                    "message": f"{len(unmatched)} tue immagini non hanno trovato "
                    "una sezione corrispondente: aggiunte all'inizio del documento",
                    "progress": 44,
                    "level": "warning",
                    "detail": "Verifica i titoli delle sezioni nella configurazione.",
                },
            )
        logger.info(
            "Injected %d user-uploaded figures across %d sections",
            sum(len(v) for v in user_figure_placements.values()),
            sum(1 for a in assigned_mandatory if a),
        )
    few_shot = state.get("few_shot", "")
    language = state.get("language", "italian")
    llm_config = _get_config(state, "writer")

    from app.core.config import settings as _settings

    use_knowledge = state.get("writer_use_knowledge", _settings.writer_use_knowledge)
    expand_threshold = _settings.writer_expand_threshold

    total = len(plan)
    done = 0
    lock = asyncio.Lock()

    # ── Group sections by chapter (part_title) preserving order ──────────────
    # Sections within a chapter are written SEQUENTIALLY so they can share
    # context (accumulated key facts). Different chapters run in PARALLEL.
    chapters: list[tuple[str, list[tuple[int, Any]]]] = []
    chapter_index: dict[str, int] = {}
    for i, s in enumerate(plan):
        pt = (s.get("part_title") or s.get("title") or "Capitolo").strip()
        if pt not in chapter_index:
            chapter_index[pt] = len(chapters)
            chapters.append((pt, []))
        chapters[chapter_index[pt]][1].append((i, s))

    await _emit(
        state,
        {
            "stage": "writing",
            "node": "write",
            "action": "chapters_planned",
            "message": f"Scrittura di {len(chapters)} capitoli in parallelo",
            "progress": 45,
            "chapters": [
                {"name": name, "sections": len(secs)} for name, secs in chapters
            ],
        },
    )

    # ── Per-chapter sequential write (parallel across chapters) ──────────────
    all_sections: list[Any] = []  # collects WrittenSection from all chapters
    established_facts: dict[str, list[str]] = {}

    async def _write_chapter(
        chapter_name: str, indexed_sections: list[tuple[int, Any]]
    ) -> list[Any]:
        """Write all sections of one chapter sequentially with shared context."""
        nonlocal done
        results: list[Any] = []
        accumulated_context: list[str] = []  # facts from previous sections

        # Build user source descriptions once per chapter.
        user_sources_context = _build_user_sources_context(user_sources)

        # Track progress within this specific chapter.
        chapter_done_count = 0
        chapter_total_count = len(indexed_sections)
        await _emit(
            state,
            {
                "stage": "writing",
                "node": "write",
                "action": "chapter_start",
                "chapter": chapter_name,
                "chapter_total": chapter_total_count,
                "message": f"Inizio capitolo: {chapter_name}",
                "progress": 45,
            },
        )

        for idx, section in indexed_sections:
            # Gather references for this section.
            section_refs: list[dict[str, str]] = []
            seen_keys: set[str] = set()
            for fname in section.get("source_filenames", []):
                for ref in refs_by_source.get(fname, []):
                    if ref["key"] not in seen_keys:
                        seen_keys.add(ref["key"])
                        section_refs.append(ref)

            # Write the section with accumulated context from previous sections.
            result = await write_section(
                section,
                documents_by_name,
                assigned_mandatory[idx],
                captions_by_path,
                few_shot,
                language,
                llm_config,
                available_refs=section_refs,
                writer_context=accumulated_context if accumulated_context else None,
                use_knowledge=use_knowledge,
                user_sources_context=user_sources_context,
            )
            results.append(result)

            # Extract key facts from the written section for the next one.
            facts = await summarize_section_context(result, llm_config)
            accumulated_context.extend(facts)
            if facts:
                logger.debug(
                    "Contesto accumulato per '%s': +%d fatti (totale %d)",
                    chapter_name,
                    len(facts),
                    len(accumulated_context),
                )

            chapter_done_count += 1
            async with lock:
                done += 1
                prog = 45 + int(30 * done / max(1, total))
                await _emit(
                    state,
                    {
                        "stage": "writing",
                        "node": "write",
                        "message": f"Scritta sezione: {section['title']}",
                        "progress": prog,
                        "completed": done,
                        "total": total,
                        "chapter": chapter_name,
                        "chapter_done": chapter_done_count,
                        "chapter_total": chapter_total_count,
                    },
                )

        # Store the accumulated context for this chapter.
        established_facts[chapter_name] = accumulated_context
        return results

    # ── Merge user-provided sources into the references pool ────────────────
    user_sources = state.get("user_sources") or []
    merged_count = 0
    if user_sources:
        from app.services.bibliography import make_key as _make_key

        pool_keys = {r["key"] for r in pool if r.get("key")}
        _used: set[str] = set(pool_keys)
        for us in user_sources:
            key = _make_key(us, _used)
            _used.add(key)
            if key and key not in pool_keys:
                pool_keys.add(key)
                merged_count += 1
                pool.append(
                    {
                        "key": key,
                        "authors": us.get("authors", ""),
                        "title": us.get("title", ""),
                        "year": us.get("year", ""),
                        "venue": us.get("venue", ""),
                        "source_filename": "__user__",
                    }
                )
        # Rebuild refs_by_source with the updated pool.
        refs_by_source = {}
        for ref in pool:
            refs_by_source.setdefault(ref["source_filename"], []).append(ref)
        logger.info(
            "Merged %d user-provided sources into references pool (total %d)",
            merged_count,
            len(pool),
        )

    # Run chapters in parallel.
    chapter_results = await asyncio.gather(
        *[_write_chapter(name, secs) for name, secs in chapters]
    )
    for cr in chapter_results:
        all_sections.extend(cr)

    # ── Expansion pass: expand sections below the character threshold ────────
    if expand_threshold > 0:
        short_indices = [
            i for i, s in enumerate(all_sections) if len(s["latex"]) < expand_threshold
        ]
        if short_indices:
            await _emit(
                state,
                {
                    "stage": "writing",
                    "node": "write",
                    "action": "expanding",
                    "message": f"Espansione di {len(short_indices)} sezioni brevi",
                    "progress": 75,
                    "detail": ", ".join(
                        all_sections[i]["title"] for i in short_indices
                    )[:200],
                },
            )
            expanded = await asyncio.gather(
                *[
                    expand_section(
                        all_sections[i], documents_by_name, language, llm_config
                    )
                    for i in short_indices
                ]
            )
            for i, exp in zip(short_indices, expanded):
                all_sections[i] = exp

    # ── Sort by order_index (preserves chapter ordering from the plan) ───────
    all_sections.sort(key=lambda s: s["order_index"])
    return {
        "sections": list(all_sections),
        "references_pool": pool,
        "established_facts": established_facts,
    }


def _build_user_sources_context(user_sources: list[dict[str, str]] | None) -> str:
    """Build a prompt section describing the user's bibliographic sources.

    The writer can draw on its knowledge of these works to enrich the text,
    even without having the full source content extracted.
    """
    if not user_sources:
        return ""
    lines: list[str] = []
    for us in user_sources:
        descr = ", ".join(
            x for x in (us.get("authors"), us.get("title"), us.get("year")) if x
        )
        venue = us.get("venue", "").strip()
        lines.append("- " + descr + (f" [{venue}]" if venue else ""))
    if not lines:
        return ""
    return (
        "\n\nFONTI FORNITE DALL'UTENTE (opere che il documento DEVE citare "
        "e il cui contenuto noto puoi usare per arricchire il testo):\n"
        + "\n".join(lines)
    )


def _group_chapters(sections: list[Any]) -> list[tuple[str, list[Any]]]:
    """Group written sections by chapter (``part_title``) preserving order."""
    chapters: list[tuple[str, list[Any]]] = []
    index: dict[str, int] = {}
    for s in sections:
        pt = (s.get("part_title") or s.get("title") or "Capitolo").strip()
        if pt not in index:
            index[pt] = len(chapters)
            chapters.append((pt, []))
        chapters[index[pt]][1].append(s)
    return chapters


async def coherence_node(state: GraphState) -> dict[str, Any]:
    """Check cross-chapter scientific coherence (best-effort).

    Compares the established facts across chapters for contradictions and
    inconsistent terminology. Failures are logged but never block the pipeline.
    Skipped entirely when ``coherence_enabled`` is False.
    """
    from app.core.config import settings as _settings

    if not _settings.coherence_enabled:
        logger.debug("Coherence check disabled via settings")
        return {}

    try:
        facts = state.get("established_facts", {}) or {}
        result = await check_coherence(facts, _get_config(state, "coherence"))
        await _emit(
            state,
            {
                "stage": "coherence",
                "node": "coherence",
                "message": f"Coerenza tra capitoli: punteggio {result.get('score', '?')}/100",
                "progress": 79,
                "level": "success" if result.get("approved") else "warning",
                "detail": "; ".join(result.get("issues", [])[:3]) or None,
            },
        )
        return {
            "coherence_issues": result.get("issues", []),
            "coherence_score": result.get("score", 100),
        }
    except Exception as exc:  # noqa: BLE001 — best-effort, don't block pipeline
        logger.warning("Coherence check failed: %s", exc)
        return {"coherence_issues": [], "coherence_score": 80}


async def citation_node(state: GraphState) -> dict[str, Any]:
    """Audit citation compliance across all sections (best-effort).

    Verifies that user-provided sources are cited, unknown keys don't appear,
    and key references aren't missed. Failures are logged but never block.
    Skipped entirely when ``citations_enabled`` is False.
    """
    from app.core.config import settings as _settings

    if not _settings.citations_enabled:
        logger.debug("Citation audit disabled via settings")
        return {}

    try:
        sections = state.get("sections", []) or []
        pool = state.get("references_pool", []) or []
        user_sources = state.get("user_sources") or []
        result = await audit_citations(
            sections=[dict(s) for s in sections],
            references_pool=[dict(r) for r in pool],
            user_sources=[dict(u) for u in user_sources] if user_sources else None,
            llm_config=_get_config(state, "citations"),
        )
        uncited = len(result.get("uncited_user_sources", []))
        unknown = len(result.get("unknown_citations", []))
        detail_parts: list[str] = []
        if uncited:
            detail_parts.append(f"{uncited} fonti utente non citate")
        if unknown:
            detail_parts.append(f"{unknown} chiavi sconosciute")
        await _emit(
            state,
            {
                "stage": "citations",
                "node": "citations",
                "message": f"Audit citazioni: punteggio {result.get('score', '?')}/100",
                "progress": 80,
                "level": "success" if result.get("approved") else "warning",
                "detail": "; ".join(detail_parts) or None,
            },
        )
        return {
            "citation_issues": result.get("issues", []),
            "citation_report": result.get("summary", ""),
        }
    except Exception as exc:  # noqa: BLE001 — best-effort, don't block pipeline
        logger.warning("Citation audit failed: %s", exc)
        return {"citation_issues": [], "citation_report": ""}


async def merge_node(state: GraphState) -> dict[str, Any]:
    """Fan-in point: waits for overview, coherence, and citations to complete.

    This node is purely a synchronization barrier. It emits a combined progress
    event so the UI can display coherence and citation results, then passes
    through to the review stage.
    """
    coherence_score = state.get("coherence_score")
    citation_issues = state.get("citation_issues") or []
    coherence_issues = state.get("coherence_issues") or []

    # Log a combined summary for the user.
    parts: list[str] = []
    if coherence_score is not None:
        parts.append(f"coerenza {coherence_score}/100")
    if citation_issues:
        parts.append(f"{len(citation_issues)} problemi citazioni")
    if coherence_issues:
        parts.append(f"{len(coherence_issues)} problemi coerenza")

    await _emit(
        state,
        {
            "stage": "merge",
            "node": "merge",
            "message": "Verifiche completate"
            + (f": {', '.join(parts)}" if parts else ""),
            "progress": 83,
            "level": "info",
        },
    )
    return {}  # pass-through — all state updates already applied by child nodes


async def overview_node(state: GraphState) -> dict[str, Any]:
    """Build a short per-chapter synopsis page shown right after the TOC.

    Only runs when the document merges more than one source or spans at least
    ``overview_min_chapters`` chapters, so single-topic documents are unaffected.
    """
    from app.core.config import settings as _settings

    if not _settings.overview_enabled:
        return {}
    sections = state.get("sections", []) or []
    chapters = _group_chapters(sections)
    n_docs = len(state.get("documents", []) or [])
    triggered = n_docs > 1 or len(chapters) >= _settings.overview_min_chapters
    if not triggered or len(chapters) < 2:
        return {}

    await _emit(
        state,
        {
            "stage": "overview",
            "node": "overview",
            "message": f"Panoramica dei {len(chapters)} capitoli",
            "progress": 81,
        },
    )

    language = state.get("language", "italian")
    lines: list[str] = []
    for pt, secs in chapters:
        titles = "; ".join(s.get("title", "") for s in secs)
        points: list[str] = []
        for s in secs:
            outline = s.get("outline") or {}
            for value in outline.values():
                if isinstance(value, list):
                    points.extend(str(x) for x in value[:3])
        pts = "; ".join(points[:6])
        lines.append(f"- Capitolo: {pt}\n  Sezioni: {titles}\n  Punti: {pts}")
    user = f"Lingua: {language}\n\nCapitoli:\n" + "\n".join(lines)

    try:
        verdict = await call_llm_structured(
            _get_config(state, "overview"),
            OVERVIEW_SYSTEM,
            user,
            schema=OverviewSchema,
            temperature=_settings.planner_temperature,
            label="overview",
        )
    except Exception as exc:  # noqa: BLE001 - overview is best-effort
        logger.warning("Generazione panoramica fallita: %s", exc)
        return {}

    by_title = {
        c.part_title.strip().lower(): c.synopsis.strip()
        for c in verdict.chapters
        if c.synopsis.strip()
    }
    items: list[str] = []
    for i, (pt, _secs) in enumerate(chapters):
        synopsis = by_title.get(pt.strip().lower(), "")
        if not synopsis and i < len(verdict.chapters):
            synopsis = verdict.chapters[i].synopsis.strip()
        if not synopsis:
            continue
        items.append(f"  \\item[{_escape(pt)}] {_escape(synopsis)}")

    if not items:
        return {}

    block = (
        "\\chapter*{Panoramica}\n"
        "\\addcontentsline{toc}{chapter}{Panoramica}\n"
        "\\begin{description}\n" + "\n".join(items) + "\n\\end{description}\n"
        "\\clearpage"
    )
    await _emit(
        state,
        {
            "stage": "overview",
            "node": "overview",
            "message": "Panoramica dei capitoli generata",
            "progress": 82,
            "level": "success",
        },
    )
    return {"overview_latex": block}


def _build_body(state: GraphState) -> list[str]:
    parts: list[str] = []
    current_part: str | None = None
    for s in state["sections"]:
        part_title = s.get("part_title")
        if part_title and part_title != current_part:
            parts.append(f"\\chapter{{{part_title}}}")
            current_part = part_title
        parts.append(s["latex"])
    # Drop any image that ended up referenced in more than one section.
    return _dedup_figure_blocks(parts)


def _ensure_mandatory_figures(state: GraphState, body_parts: list[str]) -> list[str]:
    """Append any mandatory figure not already referenced anywhere in the body."""
    mandatory: list[str] = []
    for d in state["documents"]:
        mandatory.extend(d.get("mandatory_figures", []))
    if not mandatory:
        return body_parts

    body_text = "\n".join(body_parts)
    missing = [
        p
        for p in dict.fromkeys(mandatory)
        if Path(p).name.lower() not in body_text.lower()
    ]
    if not missing:
        return body_parts

    blocks = ["\\chapter{Figure}"]
    for rel in missing:
        blocks.append(figure_latex(rel, ""))
    return body_parts + ["\n".join(blocks)]


def _assemble_initial(state: GraphState) -> str:
    """Assemble the monolithic document from the written sections (first pass)."""
    title = state.get("title", "Documento Generato")
    language = state.get("language", "italian")
    metadata = state.get("metadata") or {}
    template_id = state.get("latex_template") or "default"
    body_parts = _build_body(state)
    # Safety net: ensure every mandatory figure ends up in the document. Any
    # mandatory figure not already referenced is appended in a dedicated section.
    body_parts = _ensure_mandatory_figures(state, body_parts)
    # Optional per-chapter synopsis page, rendered right after the TOC.
    overview = state.get("overview_latex")
    if overview:
        body_parts = [overview, *body_parts]
    return assemble_document(
        title=title,
        body_parts=body_parts,
        language=language,
        author=metadata.get("author") or "PDF2LaTeX",
        subtitle=metadata.get("subtitle") or "",
        abstract=metadata.get("abstract") or "",
        cover_date=metadata.get("cover_date") or "",
        template_id=template_id,
    )


async def review_node(state: GraphState) -> dict[str, Any]:
    from app.core.config import settings as _settings

    # First pass assembles from sections; later passes recompile the document
    # the judge revised (kept in ``final_latex``).
    is_revision = bool(state.get("final_latex"))
    if is_revision:
        await _emit(
            state,
            {
                "stage": "reviewing",
                "node": "review",
                "message": "Ricompilazione dopo revisione strutturale",
                "progress": 90,
            },
        )
        latex = state["final_latex"]
    else:
        await _emit(
            state,
            {
                "stage": "reviewing",
                "node": "review",
                "message": "Revisione e compilazione",
                "progress": 84,
            },
        )
        latex = _assemble_initial(state)

    # Deterministic repair pass BEFORE pdflatex: fixes the most common
    # mechanical mistakes (unbalanced braces/environments, leftover \figref)
    # without spending an LLM round-trip.

    if _settings.latex_lint:
        latex, lint_notes = lint_latex(latex)
        if lint_notes:
            await _emit(
                state,
                {
                    "stage": "reviewing",
                    "node": "review",
                    "message": f"Lint LaTeX: {len(lint_notes)} correzioni",
                    "progress": 83,
                    "level": "info",
                    "detail": "; ".join(lint_notes[:8]),
                },
            )

    work_dir = Path(state.get("work_dir", "storage/output/_tmp"))  # type: ignore[arg-type]
    figures_src = state.get("figures_dir")
    figures_path = Path(figures_src) if figures_src else None

    # Build the bibliography deterministically and force a single instance at the
    # end of the document: keep only the references actually cited (\cite) and
    # strip any bibliography the model left between chapters.
    pool = state.get("references_pool", []) or []

    def _apply_bibliography(tex: str) -> tuple[str, str]:
        tex = strip_inline_bibliography(tex)
        bib = build_bib(pool, cited_keys(tex)) if pool else ""
        if bib.strip():
            tex = inject_bibliography(tex)
        return tex, bib

    latex, bib_content = _apply_bibliography(latex)

    # Only the user-selected figures may reach the PDF and the downloadable zip.
    allowed_figures = {
        Path(rel).name
        for d in state["documents"]
        for rel in d.get("mandatory_figures", [])
    }

    compile_log = ""
    for attempt in range(MAX_REVIEW_RETRIES + 1):
        result = write_and_compile(
            latex,
            work_dir,
            figures_src=figures_path,
            job_name="main",
            allowed_figures=allowed_figures,
            bib_content=bib_content,
        )
        if result.success:
            await _emit(
                state,
                {
                    "stage": "reviewing",
                    "node": "review",
                    "message": (
                        "Ricompilazione riuscita"
                        if is_revision
                        else "Compilazione riuscita"
                    ),
                    "progress": 92 if is_revision else 88,
                    "level": "success",
                    "tokens": tokens.snapshot(),
                },
            )
            # Remember the last version that compiled, so a later (judge)
            # revision that breaks compilation can be safely rolled back.
            return {
                "final_latex": latex,
                "pdf_path": result.pdf_path,
                "good_latex": latex,
                "good_pdf": result.pdf_path,
                "compile_log": result.log,
                "bibliography_bib": bib_content,
            }

        compile_log = result.log
        if attempt < MAX_REVIEW_RETRIES:
            await _emit(
                state,
                {
                    "stage": "reviewing",
                    "node": "review",
                    "message": f"Correzione errori (tentativo {attempt + 1})",
                    "progress": 84 + attempt * 2,
                    "level": "warning",
                    "detail": compile_error_excerpt(compile_log),
                },
            )
            latex = await review_document(
                latex, _get_config(state, "reviewer"), compile_log
            )
            if _settings.latex_lint:
                latex, _ = lint_latex(latex)
            latex, bib_content = _apply_bibliography(latex)

    # A judge revision failed to compile even after retries: roll back to the
    # last version that produced a PDF instead of shipping a broken document.
    if is_revision and state.get("good_pdf"):
        await _emit(
            state,
            {
                "stage": "reviewing",
                "node": "review",
                "message": "Revisione strutturale scartata (non compilava)",
                "progress": 94,
                "level": "warning",
                "detail": "Mantengo la versione precedente che compilava.",
            },
        )
        return {
            "final_latex": state["good_latex"],
            "pdf_path": state["good_pdf"],
            "compile_log": state.get("compile_log", ""),
            "bibliography_bib": bib_content,
        }

    # Failed to compile after retries: still return the latex for inspection.
    await _emit(
        state,
        {
            "stage": "reviewing",
            "node": "review",
            "message": "Compilazione non riuscita",
            "progress": 95,
            "level": "error",
            "detail": compile_error_excerpt(compile_log),
        },
    )
    return {
        "final_latex": latex,
        "pdf_path": None,
        "compile_log": compile_log,
        "bibliography_bib": bib_content,
    }


async def judge_node(state: GraphState) -> dict[str, Any]:
    """Evaluate the document's overall structure and request a revision if needed."""
    from app.core.config import settings as _settings

    rounds = state.get("judge_rounds", 0)
    use_vision = bool(state.get("judge_vision", _settings.judge_vision))
    await _emit(
        state,
        {
            "stage": "judging",
            "node": "judge",
            "message": "Il giudice esamina il PDF compilato",
            "progress": 90,
            "detail": (
                "analisi visiva delle pagine"
                if use_vision
                else "analisi di struttura e layout"
            ),
        },
    )

    verdict = await judge_structure(
        state["final_latex"],
        _get_config(state, "judge"),
        state.get("pdf_path"),
        state.get("compile_log"),
        use_vision=use_vision,
    )
    if verdict.approved or not verdict.issues:
        await _emit(
            state,
            {
                "stage": "judging",
                "node": "judge",
                "message": f"Struttura approvata (punteggio {verdict.score}/100)",
                "progress": 96,
                "level": "success",
                "detail": verdict.summary[:200] or None,
            },
        )
        return {"judge_action": "approve", "judge_score": verdict.score}

    await _emit(
        state,
        {
            "stage": "judging",
            "node": "judge",
            "message": f"Revisione struttura: {len(verdict.issues)} problemi",
            "progress": 91,
            "level": "warning",
            "detail": "; ".join(verdict.issues[:6]),
        },
    )
    revised = await revise_structure(
        state["final_latex"], verdict.issues, _get_config(state, "judge")
    )
    if _settings.latex_lint:
        revised, _ = lint_latex(revised)
    return {
        "final_latex": revised,
        "judge_rounds": rounds + 1,
        "judge_action": "revise",
        "judge_score": verdict.score,
    }


def _after_review(state: GraphState) -> str:
    """Route to the judge after a successful first compile, else finish."""
    from app.core.config import settings as _settings

    if not _settings.judge_enabled:
        return END
    # Don't judge a document that didn't compile.
    if not state.get("pdf_path"):
        return END
    # Stop once the allowed structural-revision rounds are exhausted.
    if state.get("judge_rounds", 0) >= _settings.judge_max_iterations:
        return END
    return "judge"


def _after_judge(state: GraphState) -> str:
    """Loop back to review+compile when the judge requested a revision."""
    if state.get("judge_action") == "revise":
        return "review"
    return END


# --------------------------------------------------------------------------- #
# Graph builder                                                                 #
# --------------------------------------------------------------------------- #
def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("analyze", analyze_node)
    graph.add_node("research", research_node)
    graph.add_node("merge_analyses", merge_analyses_node)
    graph.add_node("plan", plan_node)
    graph.add_node("write", write_node)
    graph.add_node("overview", overview_node)
    graph.add_node("coherence", coherence_node)
    graph.add_node("citations", citation_node)
    graph.add_node("merge", merge_node)
    graph.add_node("review", review_node)
    graph.add_node("judge", judge_node)

    # START → analyze (if PDFs) and/or research (if research_mode).
    # Both write to separate state keys; merge_analyses combines them.
    def _route_start(state: GraphState) -> list[str]:
        routes: list[str] = []
        if state.get("documents"):
            routes.append("analyze")
        if state.get("research_mode"):
            routes.append("research")
        return routes if routes else ["analyze"]  # default for safety

    graph.add_conditional_edges(
        START,
        _route_start,
        {
            "analyze": "analyze",
            "research": "research",
        },
    )
    graph.add_edge("analyze", "merge_analyses")
    graph.add_edge("research", "merge_analyses")
    graph.add_edge("merge_analyses", "plan")
    # Diamond fan-out: write → overview, coherence, citations (parallel)
    graph.add_edge("plan", "write")
    graph.add_edge("write", "overview")
    graph.add_edge("write", "coherence")
    graph.add_edge("write", "citations")
    # Fan-in: all three converge on merge before review
    graph.add_edge("overview", "merge")
    graph.add_edge("coherence", "merge")
    graph.add_edge("citations", "merge")
    graph.add_edge("merge", "review")
    graph.add_conditional_edges("review", _after_review, {"judge": "judge", END: END})
    graph.add_conditional_edges("judge", _after_judge, {"review": "review", END: END})

    return graph.compile()


async def run_pipeline(
    documents: list[dict[str, Any]],
    user_prompt: str,
    language: str,
    llm_config: dict[str, Any],
    few_shot: str,
    work_dir: Path,
    figures_dir: Path | None,
    metadata: dict[str, Any] | None = None,
    structure_hint: str = "",
    progress=None,
    judge_vision: bool | None = None,
    writer_use_knowledge: bool | None = None,
    user_sources: list[dict[str, str]] | None = None,
    research_mode: bool = False,
    web_tool_configs: list[dict[str, Any]] | None = None,
    user_figure_placements: dict[str, list[tuple[str, str]]] | None = None,
    role_configs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the full pipeline and return the final state."""
    from app.core.config import settings as _settings

    app = build_graph()
    initial: dict[str, Any] = {
        "documents": documents,
        "user_prompt": user_prompt,
        "language": language,
        "llm_config": llm_config,
        "role_configs": role_configs,
        "few_shot": few_shot,
        "work_dir": str(work_dir),
        "figures_dir": str(figures_dir) if figures_dir else None,
        "metadata": metadata or {},
        "structure_hint": structure_hint,
        "latex_template": (metadata or {}).get("latex_template", "default"),
        "progress": progress,
        "judge_vision": (
            _settings.judge_vision if judge_vision is None else judge_vision
        ),
        "writer_use_knowledge": (
            _settings.writer_use_knowledge
            if writer_use_knowledge is None
            else writer_use_knowledge
        ),
        "user_sources": user_sources or [],
        "research_mode": research_mode,
        "web_tool_configs": web_tool_configs or [],
        "user_figure_placements": user_figure_placements or {},
    }
    # The produced keys (analyses/plan/sections/...) are filled in by the nodes;
    # the initial state only carries the inputs, hence the cast.
    final = await app.ainvoke(cast(GraphState, initial))
    return final
