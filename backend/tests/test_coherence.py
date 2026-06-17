"""Tests for coherence checker: cross-chapter contradiction detection.

All LLM calls are mocked — no network dependencies.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.coherence import check_coherence

# ── Early returns (no LLM call needed) ────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_facts_returns_approved(fake_llm_config):
    """Empty or None facts dict returns approved=True without LLM call."""
    with patch("app.agents.coherence.call_llm_structured", AsyncMock()) as mock:
        result = await check_coherence({}, fake_llm_config)
    assert result["approved"] is True
    assert result["score"] == 100
    assert result["issues"] == []
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_single_chapter_skipped(fake_llm_config):
    """Single chapter (need 2+ to compare) returns approved without LLM call."""
    facts = {"Capitolo 1": ["Fatto A", "Fatto B"]}
    with patch("app.agents.coherence.call_llm_structured", AsyncMock()) as mock:
        result = await check_coherence(facts, fake_llm_config)
    assert result["approved"] is True
    assert result["score"] == 100
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_empty_values_skipped(fake_llm_config):
    """Chapters with no facts produce no prompt lines → approved."""
    facts: dict[str, list[str]] = {"Capitolo 1": [], "Capitolo 2": []}
    with patch("app.agents.coherence.call_llm_structured", AsyncMock()) as mock:
        result = await check_coherence(facts, fake_llm_config)
    assert result["approved"] is True
    mock.assert_not_called()


# ── LLM-mediated decisions ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coherent_chapters_approved(fake_llm_config):
    """Consistent facts across chapters → LLM returns approved=True."""
    from app.agents.schemas import CoherenceSchema

    facts: dict[str, list[str]] = {
        "Capitolo 1": [
            "Il ML usa dati etichettati",
            "La regressione predice valori continui",
        ],
        "Capitolo 2": [
            "La classificazione assegna etichette discrete",
            "Le CNN elaborano immagini",
        ],
    }
    verdict = CoherenceSchema(approved=True, score=95, issues=[], summary="Coerente")

    with patch(
        "app.agents.coherence.call_llm_structured", AsyncMock(return_value=verdict)
    ) as mock:
        result = await check_coherence(facts, fake_llm_config)

    assert mock.call_count == 1
    assert result["approved"] is True
    assert result["score"] == 95
    assert result["issues"] == []


@pytest.mark.asyncio
async def test_contradiction_detected(fake_llm_config):
    """Contradictory facts → LLM returns approved=False with issues."""
    from app.agents.schemas import CoherenceSchema

    facts: dict[str, list[str]] = {
        "Capitolo 1": ["L'apprendimento supervisionato richiede sempre etichette"],
        "Capitolo 3": ["L'apprendimento supervisionato può funzionare senza etichette"],
    }
    issues = [
        "Contraddizione: Cap 1 dice che il supervisionato richiede etichette, Cap 3 dice il contrario",
    ]
    verdict = CoherenceSchema(
        approved=False, score=40, issues=issues, summary="Grave contraddizione"
    )

    with patch(
        "app.agents.coherence.call_llm_structured", AsyncMock(return_value=verdict)
    ) as mock:
        result = await check_coherence(facts, fake_llm_config)

    assert mock.call_count == 1
    assert result["approved"] is False
    assert result["score"] == 40
    assert len(result["issues"]) == 1
    assert "Contraddizione" in result["issues"][0]


@pytest.mark.asyncio
async def test_terminology_inconsistency(fake_llm_config):
    """Same concept called by different names → flagged as issue."""
    from app.agents.schemas import CoherenceSchema

    facts: dict[str, list[str]] = {
        "Capitolo 1": ["Il modello Transformer usa self-attention"],
        "Capitolo 2": ["Il modello Trasformatore utilizza l'auto-attenzione"],
    }
    verdict = CoherenceSchema(
        approved=False,
        score=65,
        issues=["Incoerenza terminologica: 'Transformer' vs 'Trasformatore'"],
        summary="Terminologia incoerente",
    )

    with patch(
        "app.agents.coherence.call_llm_structured", AsyncMock(return_value=verdict)
    ):
        result = await check_coherence(facts, fake_llm_config)

    assert result["approved"] is False
    assert "Transformer" in result["issues"][0]


@pytest.mark.asyncio
async def test_substantial_repetition(fake_llm_config):
    """Identical facts in multiple chapters → flagged."""
    from app.agents.schemas import CoherenceSchema

    facts: dict[str, list[str]] = {
        "Capitolo 1": ["La regressione lineare minimizza l'MSE"],
        "Capitolo 2": ["La regressione lineare minimizza l'MSE"],
    }
    verdict = CoherenceSchema(
        approved=False,
        score=70,
        issues=[
            "Ripetizione sostanziale: 'La regressione lineare minimizza l'MSE' appare in Cap 1 e Cap 2"
        ],
        summary="Ripetizioni tra capitoli",
    )

    with patch(
        "app.agents.coherence.call_llm_structured", AsyncMock(return_value=verdict)
    ):
        result = await check_coherence(facts, fake_llm_config)

    assert result["approved"] is False
    assert result["score"] == 70
    assert "Ripetizione" in result["issues"][0]


# ── LLM failure fallback ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_failure_returns_safe_fallback(fake_llm_config):
    """When the LLM call raises, return approved=True with default score."""
    facts: dict[str, list[str]] = {
        "Capitolo 1": ["Fatto A"],
        "Capitolo 2": ["Fatto B"],
    }
    with patch(
        "app.agents.coherence.call_llm_structured",
        AsyncMock(side_effect=RuntimeError("Connection refused")),
    ):
        result = await check_coherence(facts, fake_llm_config)

    assert result["approved"] is True
    assert result["score"] == 80
    assert result["issues"] == []
    assert result["summary"] == ""


# ── Multiple chapters (> 2) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_three_chapters_compared(fake_llm_config):
    """Three chapters are all included in the prompt."""
    from app.agents.schemas import CoherenceSchema

    facts: dict[str, list[str]] = {
        "Capitolo 1": ["Fatto 1A"],
        "Capitolo 2": ["Fatto 2A"],
        "Capitolo 3": ["Fatto 3A"],
    }
    verdict = CoherenceSchema(approved=True, score=90, issues=[], summary="Ok")

    with patch(
        "app.agents.coherence.call_llm_structured", AsyncMock(return_value=verdict)
    ) as mock:
        result = await check_coherence(facts, fake_llm_config)

    assert mock.call_count == 1
    # All three chapter names should appear in the user prompt.
    user_prompt: str = mock.call_args[0][2]
    assert "Capitolo 1" in user_prompt
    assert "Capitolo 2" in user_prompt
    assert "Capitolo 3" in user_prompt
    assert result["approved"] is True
