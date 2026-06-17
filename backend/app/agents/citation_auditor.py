r"""Citation auditor agent: verify that bibliographic sources are properly used.

After all sections are written, this agent scans the LaTeX for \cite commands
and cross-references them against the available reference pool. It flags:
* User-provided sources that were never cited
* Unknown citation keys that don't exist in the pool
* Key source references that should have been cited but weren't
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.prompts import CITATION_AUDITOR_SYSTEM
from app.agents.schemas import CitationAuditSchema
from app.agents.utils import call_llm_structured
from app.core.logging import get_logger

logger = get_logger("citation_auditor")

_CITE_RE = re.compile(r"\\cite\{([^}]+)\}")


def _extract_cited_keys(latex_parts: list[str]) -> set[str]:
    """Pull every citation key referenced via \\cite anywhere in the body."""
    keys: set[str] = set()
    for part in latex_parts:
        for match in _CITE_RE.finditer(part):
            for k in match.group(1).split(","):
                key = k.strip()
                if key:
                    keys.add(key)
    return keys


async def audit_citations(
    sections: list[dict[str, Any]],
    references_pool: list[dict[str, str]],
    user_sources: list[dict[str, str]] | None,
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    """Audit citation compliance across all written sections.

    Args:
        sections: List of WrittenSection dicts (with ``latex`` and ``title``).
        references_pool: All available references with citation keys.
        user_sources: User-provided bibliographic sources to verify were cited.
        llm_config: LLM provider configuration.

    Returns:
        dict with ``approved``, ``score``, ``uncited_user_sources``,
        ``unknown_citations``, ``issues``, ``summary``.
    """
    # ── Deterministic checks ────────────────────────────────────────────────
    pool_keys = {r["key"] for r in references_pool if r.get("key")}
    user_keys: set[str] = set()
    if user_sources:
        from app.services.bibliography import make_key

        _used: set[str] = set()
        for us in user_sources:
            key = make_key(us, _used)
            _used.add(key)
            user_keys.add(key)

    # Scan all sections for \cite commands.
    body_text = "\n".join(s.get("latex", "") for s in sections)
    cited_keys = _extract_cited_keys([body_text])

    unknown = sorted(cited_keys - pool_keys)
    uncited_user = sorted(user_keys - cited_keys) if user_keys else []

    # ── LLM review (best-effort, enriches the deterministic findings) ────────
    user_sources_list = ""
    if user_sources:
        lines = []
        _used2: set[str] = set()
        for us in user_sources:
            descr = ", ".join(
                x for x in (us.get("authors"), us.get("title"), us.get("year")) if x
            )
            key = make_key(us, _used2)
            _used2.add(key)
            lines.append(f"- {key}: {descr}")
        if lines:
            user_sources_list = (
                "\n\nFonti fornite DALL'UTENTE (devono essere citate!):\n"
                + "\n".join(lines)
            )

    ref_list = ""
    if references_pool:
        ref_list_lines = []
        for r in references_pool[:30]:  # cap to avoid huge prompts
            descr = ", ".join(
                x for x in (r.get("authors"), r.get("title"), r.get("year")) if x
            )
            ref_list_lines.append(f"- {r.get('key', '?')}: {descr}")
        ref_list = "\n".join(ref_list_lines)

    sections_summary = "\n".join(
        f"Sezione: {s.get('title', '?')} ({len(s.get('latex', ''))} caratteri)"
        for s in sections[:20]
    )

    user = (
        f"Sezioni del documento:\n{sections_summary}\n\n"
        f"Chiavi CITATE nel documento: {', '.join(sorted(cited_keys)) or '(nessuna)'}\n\n"
        f"Riferimenti disponibili (pool):\n{ref_list}{user_sources_list}"
    )

    try:
        verdict = await call_llm_structured(
            llm_config,
            CITATION_AUDITOR_SYSTEM,
            user,
            schema=CitationAuditSchema,
            temperature=0.0,
            label="citation-audit",
        )
        # Merge deterministic findings.
        all_uncited = sorted(
            set(uncited_user + list(verdict.uncited_user_sources or []))
        )
        all_unknown = sorted(set(unknown + list(verdict.unknown_citations or [])))
        approved = verdict.approved and not all_unknown and not all_uncited
        score = max(
            0, (verdict.score or 80) - len(all_unknown) * 10 - len(all_uncited) * 15
        )

        logger.info(
            "Citation audit: approved=%s score=%s uncited_user=%d unknown=%d issues=%d",
            approved,
            score,
            len(all_uncited),
            len(all_unknown),
            len(verdict.issues or []),
        )
        return {
            "approved": approved,
            "score": score,
            "uncited_user_sources": all_uncited,
            "unknown_citations": all_unknown,
            "issues": list(verdict.issues or []),
            "summary": verdict.summary or "",
        }
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.warning("Citation audit failed: %s", exc)
        return {
            "approved": not unknown,
            "score": max(0, 100 - len(unknown) * 10 - len(uncited_user) * 15),
            "uncited_user_sources": uncited_user,
            "unknown_citations": unknown,
            "issues": [],
            "summary": "",
        }
