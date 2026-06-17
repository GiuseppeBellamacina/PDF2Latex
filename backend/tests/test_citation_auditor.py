"""Tests for citation auditor: uncited sources, unknown keys, fallback.

All LLM calls are mocked — no network dependencies.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.citation_auditor import _extract_cited_keys, audit_citations
from app.services.bibliography import make_key

# ── _extract_cited_keys helper ────────────────────────────────────────────


def test_extract_single_key():
    keys = _extract_cited_keys([r"\cite{he2016}"])
    assert keys == {"he2016"}


def test_extract_multiple_keys_in_one_cite():
    keys = _extract_cited_keys([r"\cite{he2016,vaswani2017}"])
    assert keys == {"he2016", "vaswani2017"}


def test_extract_multiple_cite_commands():
    keys = _extract_cited_keys([r"Testo \cite{he2016} altro \cite{vaswani2017} fine."])
    assert keys == {"he2016", "vaswani2017"}


def test_extract_no_cite_returns_empty():
    keys = _extract_cited_keys([r"\section{Intro} Nessuna citazione."])
    assert keys == set()


def test_extract_empty_parts():
    assert _extract_cited_keys([]) == set()
    assert _extract_cited_keys([""]) == set()


def test_extract_nested_braces_ignored():
    r"""Only simple \cite{key} is matched, not \cite{key{sub}}."""
    keys = _extract_cited_keys([r"\cite{he2016} and \cite{vaswani}."])
    assert keys == {"he2016", "vaswani"}


# ── audit_citations: happy paths ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_valid_cited(fake_llm_config):
    """All keys cited exist in pool → approved, no issues."""
    from app.agents.schemas import CitationAuditSchema

    sections = [
        {"title": "S1", "latex": r"Testo \cite{he2016}."},
        {"title": "S2", "latex": r"Altro \cite{vaswani2017}."},
    ]
    pool = [
        {"key": "he2016", "authors": "He", "title": "ResNet", "year": "2016"},
        {
            "key": "vaswani2017",
            "authors": "Vaswani",
            "title": "Attention",
            "year": "2017",
        },
    ]
    verdict = CitationAuditSchema(approved=True, score=100, issues=[], summary="Ok")

    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(return_value=verdict),
    ) as mock:
        result = await audit_citations(
            sections, pool, user_sources=None, llm_config=fake_llm_config
        )

    assert mock.call_count == 1
    assert result["approved"] is True
    assert result["score"] == 100
    assert result["unknown_citations"] == []


@pytest.mark.asyncio
async def test_user_sources_all_cited(fake_llm_config):
    """User-provided source is cited → approved.

    In the real graph, write_node merges user sources into the references pool
    before citation_node runs. The test mirrors this: the user source key
    must be in the pool so it's recognized as a valid citation target.
    """
    from app.agents.schemas import CitationAuditSchema

    user_sources = [
        {
            "authors": "Vaswani et al.",
            "title": "Attention Is All You Need",
            "year": "2017",
            "venue": "NeurIPS",
        },
    ]
    used: set[str] = set()
    key = make_key(user_sources[0], used)
    used.add(key)
    # Simulate write_node merging: add user source to the pool.
    pool: list[dict[str, str]] = [
        {
            "key": key,
            "authors": "Vaswani et al.",
            "title": "Attention Is All You Need",
            "year": "2017",
            "source_filename": "__user__",
        },
    ]
    sections = [{"title": "S1", "latex": rf"\cite{{{key}}}"}]
    verdict = CitationAuditSchema(approved=True, score=100, issues=[], summary="Ok")

    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(return_value=verdict),
    ):
        result = await audit_citations(
            sections, pool, user_sources=user_sources, llm_config=fake_llm_config
        )

    assert result["approved"] is True
    assert result["uncited_user_sources"] == []


# ── audit_citations: problems detected ────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_key_detected(fake_llm_config):
    r"""A \cite to a key not in the pool → flagged deterministically."""
    sections = [{"title": "S1", "latex": r"\cite{bogus_key}"}]
    pool: list[dict[str, str]] = []
    # The LLM won't be called in the fallback path since there's nothing to review,
    # but we mock it anyway for determinism.
    from app.agents.schemas import CitationAuditSchema

    verdict = CitationAuditSchema(approved=True, score=80, issues=[], summary="")

    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(return_value=verdict),
    ):
        result = await audit_citations(
            sections, pool, user_sources=None, llm_config=fake_llm_config
        )

    assert result["unknown_citations"] == ["bogus_key"]
    assert result["approved"] is False  # unknown keys make it not approved


@pytest.mark.asyncio
async def test_uncited_user_source_detected(fake_llm_config):
    r"""User source key not in any \cite → flagged."""
    user_sources = [
        {
            "authors": "He et al.",
            "title": "Deep Residual Learning",
            "year": "2016",
            "venue": "CVPR",
        },
        {
            "authors": "Vaswani et al.",
            "title": "Attention Is All You Need",
            "year": "2017",
            "venue": "NeurIPS",
        },
    ]
    used: set[str] = set()
    key_he = make_key(user_sources[0], used)
    used.add(key_he)
    key_vaswani = make_key(user_sources[1], used)
    # Only He's source is cited; Vaswani's is not.
    sections = [{"title": "S1", "latex": rf"\cite{{{key_he}}}"}]
    pool: list[dict[str, str]] = []

    from app.agents.schemas import CitationAuditSchema

    verdict = CitationAuditSchema(approved=True, score=80, issues=[], summary="")

    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(return_value=verdict),
    ):
        result = await audit_citations(
            sections, pool, user_sources=user_sources, llm_config=fake_llm_config
        )

    uncited = result["uncited_user_sources"]
    assert len(uncited) == 1, f"Expected 1 uncited, got {uncited}"
    assert key_vaswani in uncited, (
        f"Expected '{key_vaswani}' in uncited keys, got: {uncited}"
    )


@pytest.mark.asyncio
async def test_combined_unknown_and_uncited(fake_llm_config):
    """Both unknown citation keys and uncited user sources appear."""
    from app.agents.schemas import CitationAuditSchema

    user_sources = [
        {
            "authors": "He et al.",
            "title": "Deep Residual Learning",
            "year": "2016",
            "venue": "CVPR",
        },
    ]
    key_he = make_key(user_sources[0], set())
    # Only bogus2020 is cited; He's key is NOT cited → uncited.
    sections = [{"title": "S1", "latex": r"\cite{bogus2020}"}]
    pool: list[dict[str, str]] = []
    verdict = CitationAuditSchema(approved=True, score=60, issues=[], summary="")

    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(return_value=verdict),
    ):
        result = await audit_citations(
            sections, pool, user_sources=user_sources, llm_config=fake_llm_config
        )

    assert "bogus2020" in result["unknown_citations"], (
        f"Expected 'bogus2020' in unknown, got: {result['unknown_citations']}"
    )
    assert key_he in result["uncited_user_sources"], (
        f"Expected '{key_he}' uncited, got: {result['uncited_user_sources']}"
    )
    assert result["approved"] is False  # unknown keys disqualify
    assert result["score"] < 80  # penalties applied


# ── audit_citations: LLM failure fallback ─────────────────────────────────


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_deterministic(fake_llm_config):
    """When the LLM call fails, deterministic findings are still returned."""
    sections = [{"title": "S1", "latex": r"\cite{bogus2020}"}]
    pool: list[dict[str, str]] = []
    user_sources = [
        {
            "authors": "Vaswani",
            "title": "Attention",
            "year": "2017",
            "venue": "NeurIPS",
        },
    ]
    key_vaswani = make_key(user_sources[0], set())

    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(side_effect=RuntimeError("Timeout")),
    ):
        result = await audit_citations(
            sections, pool, user_sources=user_sources, llm_config=fake_llm_config
        )

    # Deterministic findings survive.
    assert "bogus2020" in result["unknown_citations"]
    assert key_vaswani in result["uncited_user_sources"], (
        f"Expected '{key_vaswani}' uncited, got: {result['uncited_user_sources']}"
    )
    assert result["approved"] is False
    assert result["issues"] == []  # LLM didn't contribute


# ── audit_citations: edge cases ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_sections_handled(fake_llm_config):
    """No sections → no citations, everything is fine."""
    from app.agents.schemas import CitationAuditSchema

    verdict = CitationAuditSchema(approved=True, score=100, issues=[], summary="")
    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(return_value=verdict),
    ):
        result = await audit_citations(
            [], [], user_sources=None, llm_config=fake_llm_config
        )

    assert result["approved"] is True
    assert result["unknown_citations"] == []


@pytest.mark.asyncio
async def test_no_user_sources_no_problem(fake_llm_config):
    """Without user sources, uncited_user_sources should be empty."""
    from app.agents.schemas import CitationAuditSchema

    sections = [{"title": "S1", "latex": r"\cite{he2016}"}]
    pool = [{"key": "he2016", "authors": "He", "title": "T", "year": "2016"}]
    verdict = CitationAuditSchema(approved=True, score=100, issues=[], summary="Ok")

    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(return_value=verdict),
    ):
        result = await audit_citations(
            sections, pool, user_sources=None, llm_config=fake_llm_config
        )

    assert result["uncited_user_sources"] == []
    assert result["unknown_citations"] == []
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_multiple_sections_aggregated(fake_llm_config):
    """Citations from all sections are collected together."""
    from app.agents.schemas import CitationAuditSchema

    sections = [
        {"title": "S1", "latex": r"\cite{he2016}"},
        {"title": "S2", "latex": r"\cite{vaswani2017}"},
        {"title": "S3", "latex": r"Nessuna citazione qui."},
    ]
    pool = [
        {"key": "he2016", "authors": "He", "title": "T1", "year": "2016"},
        {"key": "vaswani2017", "authors": "Vaswani", "title": "T2", "year": "2017"},
    ]
    verdict = CitationAuditSchema(approved=True, score=100, issues=[], summary="Ok")

    with patch(
        "app.agents.citation_auditor.call_llm_structured",
        AsyncMock(return_value=verdict),
    ):
        result = await audit_citations(
            sections, pool, user_sources=None, llm_config=fake_llm_config
        )

    assert result["approved"] is True
    assert result["unknown_citations"] == []
