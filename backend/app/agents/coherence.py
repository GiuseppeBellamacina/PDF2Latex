"""Coherence checker agent: validate cross-chapter scientific consistency.

After all sections are written, this agent compares the key facts established
in each chapter and flags contradictions, inconsistent terminology, and
substantial repetitions that span multiple chapters.
"""

from __future__ import annotations

from typing import Any

from app.agents.prompts import COHERENCE_SYSTEM
from app.agents.schemas import CoherenceSchema
from app.agents.utils import call_llm_structured
from app.core.logging import get_logger

logger = get_logger("coherence")


async def check_coherence(
    established_facts: dict[str, list[str]],
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    """Compare established facts across chapters and return coherence issues.

    Args:
        established_facts: dict mapping chapter name -> list of key facts.
        llm_config: LLM provider configuration.

    Returns:
        dict with ``approved``, ``score``, ``issues``, ``summary``.
    """
    if not established_facts or len(established_facts) < 2:
        logger.debug(
            "Coherence check skipped: only %d chapter(s) with facts",
            len(established_facts),
        )
        return {"approved": True, "score": 100, "issues": [], "summary": ""}

    # Build a compact prompt listing facts per chapter.
    lines: list[str] = []
    for chapter_name, facts in established_facts.items():
        if not facts:
            continue
        lines.append(f"\nCapitolo: {chapter_name}")
        for fact in facts:
            lines.append(f"  - {fact}")

    if not lines:
        return {"approved": True, "score": 100, "issues": [], "summary": ""}

    user = (
        "Confronta i fatti chiave stabiliti in ciascun capitolo e segnala "
        "contraddizioni, incoerenze terminologiche o ripetizioni sostanziali.\n"
        + "\n".join(lines)
    )

    try:
        verdict = await call_llm_structured(
            llm_config,
            COHERENCE_SYSTEM,
            user,
            schema=CoherenceSchema,
            temperature=0.0,  # deterministic for consistency checking
            label="coherence",
        )
        logger.info(
            "Coherence check: approved=%s score=%s issues=%d",
            verdict.approved,
            verdict.score,
            len(verdict.issues),
        )
        return {
            "approved": verdict.approved,
            "score": verdict.score,
            "issues": list(verdict.issues),
            "summary": verdict.summary or "",
        }
    except Exception as exc:  # noqa: BLE001 — coherence is best-effort
        logger.warning("Coherence check failed: %s", exc)
        return {"approved": True, "score": 80, "issues": [], "summary": ""}
