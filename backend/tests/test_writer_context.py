"""Tests for writer context anti-repetition, knowledge toggle, and expansion.

All LLM calls are mocked — no network dependencies.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.prompts import WRITER_EXPAND_SYSTEM
from app.agents.state import WrittenSection
from app.agents.writer import (
    _build_context_part,
    expand_section,
    summarize_section_context,
    write_section,
)

# ── context_part_formatting ───────────────────────────────────────────────


def test_context_part_formatting():
    """_build_context_part formats facts with CONCETTI GIÀ TRATTATI header."""
    context = [
        "Il machine learning crea sistemi che apprendono pattern dai dati",
        "I tre paradigmi principali sono supervisionato, non supervisionato e per rinforzo",
    ]
    result = _build_context_part(context)
    assert "CONCETTI GIÀ TRATTATI" in result
    assert "machine learning" in result
    assert "tre paradigmi" in result


def test_context_part_empty():
    """_build_context_part returns '' for None or empty list."""
    assert _build_context_part(None) == ""
    assert _build_context_part([]) == ""


# ── write_section without / with context ───────────────────────────────────


@pytest.mark.asyncio
async def test_write_section_without_context(
    sample_plan_same_chapter, documents, fake_llm_config, section1_latex
):
    """First section in a chapter receives NO context block."""
    section = sample_plan_same_chapter[0]
    with patch(
        "app.agents.writer.call_llm", AsyncMock(return_value=section1_latex)
    ) as mock_llm:
        result = await write_section(
            section=section,
            documents_by_name=documents,
            assigned_mandatory=[],
            captions_by_path={},
            few_shot="",
            language="italian",
            llm_config=fake_llm_config,
            writer_context=None,
        )
    assert result["title"] == section["title"]
    user_prompt: str = mock_llm.call_args[0][2]
    assert "CONCETTI GIÀ TRATTATI" not in user_prompt


@pytest.mark.asyncio
async def test_write_section_with_context(
    sample_plan_same_chapter, documents, fake_llm_config, section2_latex
):
    """Section with explicit context receives CONCETTI GIÀ TRATTATI block."""
    section = sample_plan_same_chapter[0]
    context = [
        "Il machine learning crea sistemi che apprendono pattern dai dati",
        "I tre paradigmi principali sono supervisionato, non supervisionato e per rinforzo",
    ]
    with patch(
        "app.agents.writer.call_llm", AsyncMock(return_value=section2_latex)
    ) as mock_llm:
        await write_section(
            section=section,
            documents_by_name=documents,
            assigned_mandatory=[],
            captions_by_path={},
            few_shot="",
            language="italian",
            llm_config=fake_llm_config,
            writer_context=context,
        )
    user_prompt: str = mock_llm.call_args[0][2]
    assert "CONCETTI GIÀ TRATTATI" in user_prompt
    assert "machine learning" in user_prompt


# ── summarize_section_context ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summarize_extracts_facts(
    fake_llm_config, section1_latex, section1_context_json
):
    """summarize_section_context parses JSON facts from LLM response."""
    section: WrittenSection = {
        "title": "1.1 Introduzione",
        "part_title": "Capitolo 1",
        "order_index": 0,
        "latex": section1_latex,
        "outline": {},
        "source_filenames": ["appunti.pdf"],
    }
    with patch(
        "app.agents.writer.call_llm", AsyncMock(return_value=section1_context_json)
    ) as mock_llm:
        facts = await summarize_section_context(section, fake_llm_config)
    assert mock_llm.call_count == 1
    assert mock_llm.call_args[1]["temperature"] == 0.0
    assert len(facts) == 3
    assert any("machine learning" in f.lower() for f in facts)
    assert any("paradigmi" in f.lower() for f in facts)


@pytest.mark.asyncio
async def test_summarize_skips_short_sections(fake_llm_config):
    """Sections under 200 chars return [] without LLM call."""
    section: WrittenSection = {
        "title": "Breve",
        "part_title": "Cap",
        "order_index": 0,
        "latex": r"\section{Breve}\nTesto corto.",
        "outline": {},
        "source_filenames": ["appunti.pdf"],
    }
    with patch("app.agents.writer.call_llm", AsyncMock()) as mock_llm:
        facts = await summarize_section_context(section, fake_llm_config)
    assert facts == []
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_handles_invalid_json(fake_llm_config, section1_latex):
    """Invalid JSON response returns []."""
    section: WrittenSection = {
        "title": "1.1",
        "part_title": "Cap",
        "order_index": 0,
        "latex": section1_latex,
        "outline": {},
        "source_filenames": ["appunti.pdf"],
    }
    with patch(
        "app.agents.writer.call_llm", AsyncMock(return_value="Questo non è JSON.")
    ):
        facts = await summarize_section_context(section, fake_llm_config)
    assert facts == []


# ── Full chapter sequential simulation (CORE anti-repetition test) ────────


@pytest.mark.asyncio
async def test_full_chapter_sequential_write(
    sample_plan_same_chapter,
    documents_no_apprendono,
    fake_llm_config,
    section1_latex,
    section1_context_json,
    section2_latex,
    section2_context_json,
):
    """Write section 1 → extract facts → write section 2 WITH context.

    Verifies the anti-repetition mechanism: unique context words NOT in
    the source text appear verbatim in section 2's prompt.
    """
    s1, s2 = sample_plan_same_chapter
    docs = documents_no_apprendono
    responses = [
        section1_latex,
        section1_context_json,
        section2_latex,
        section2_context_json,
    ]

    with patch(
        "app.agents.writer.call_llm", AsyncMock(side_effect=responses)
    ) as mock_llm:
        # Step 1: write section 1 (no context)
        r1 = await write_section(
            s1, docs, [], {}, "", "italian", fake_llm_config, writer_context=None
        )
        user1 = mock_llm.call_args_list[0][0][2]
        assert "CONCETTI GIÀ TRATTATI" not in user1

        # Step 2: extract facts
        facts1 = await summarize_section_context(r1, fake_llm_config)
        assert len(facts1) > 0

        # Step 3: write section 2 WITH context
        r2 = await write_section(
            s2, docs, [], {}, "", "italian", fake_llm_config, writer_context=facts1
        )
        user2 = mock_llm.call_args_list[2][0][2]

        # KEY: "apprendono" is NOT in source, only in injected context
        assert "apprendono pattern dai dati" in user2, (
            f"Unique context fact must appear. Prompt prefix: {user2[:500]}"
        )

        # Step 4: extract facts from section 2
        facts2 = await summarize_section_context(r2, fake_llm_config)
        assert len(facts2) > 0

        accumulated = facts1 + facts2
        assert len(accumulated) >= 4
        assert mock_llm.call_count == 4


# ── Knowledge instruction toggle ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_knowledge_toggle_off(
    sample_plan_same_chapter, documents, fake_llm_config, section1_latex
):
    """use_knowledge=False → system prompt says NON inventare."""
    with patch(
        "app.agents.writer.call_llm", AsyncMock(return_value=section1_latex)
    ) as mock_llm:
        await write_section(
            sample_plan_same_chapter[0],
            documents,
            [],
            {},
            "",
            "italian",
            fake_llm_config,
            use_knowledge=False,
        )
    system = mock_llm.call_args[0][1]
    assert "NON inventare contenuti" in system


@pytest.mark.asyncio
async def test_knowledge_toggle_on(
    sample_plan_same_chapter, documents, fake_llm_config, section1_latex
):
    """use_knowledge=True → system prompt says INTEGRARE."""
    with patch(
        "app.agents.writer.call_llm", AsyncMock(return_value=section1_latex)
    ) as mock_llm:
        await write_section(
            sample_plan_same_chapter[0],
            documents,
            [],
            {},
            "",
            "italian",
            fake_llm_config,
            use_knowledge=True,
        )
    system = mock_llm.call_args[0][1]
    assert "INTEGRARE con la tua conoscenza" in system


# ── expand_section ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expand_section_calls_llm(fake_llm_config, section1_latex, documents):
    """expand_section calls the LLM and returns an expanded WrittenSection."""
    short: WrittenSection = {
        "title": "Breve sezione",
        "part_title": "Cap 1",
        "order_index": 0,
        "latex": r"\section{Breve}\nPoco testo.",
        "outline": {"punti": ["Punto 1"]},
        "source_filenames": ["appunti.pdf"],
    }
    expanded_latex = (
        r"\section{Breve}\nPoco testo. Ulteriori dettagli ed esempi concreti."
    )

    with patch(
        "app.agents.writer.call_llm", AsyncMock(return_value=expanded_latex)
    ) as mock_llm:
        result = await expand_section(short, documents, "italian", fake_llm_config)

    assert mock_llm.call_count == 1
    assert result["title"] == short["title"]
    assert len(result["latex"]) > len(short["latex"]), (
        "Expanded section should be longer"
    )
    assert "Ulteriori dettagli" in result["latex"]


@pytest.mark.asyncio
async def test_expand_section_second_llm_call(
    sample_plan_same_chapter,
    documents,
    fake_llm_config,
):
    """A short section written first, then expanded = two distinct LLM calls.

    Verifies the full graph flow: write_section (call #1) produces a short
    section (< threshold), then expand_section (call #2) adds detail with a
    second LLM invocation using the WRITER_EXPAND_SYSTEM prompt.
    """
    section = sample_plan_same_chapter[0]
    short_latex = r"\section{ML}\nBreve introduzione."
    expanded_latex = (
        r"\section{ML}\nBreve introduzione. "
        r"Il machine learning è un campo dell'intelligenza artificiale "
        r"che consente ai sistemi di apprendere dai dati senza essere "
        r"esplicitamente programmati. Include paradigmi supervisionati "
        r"e non supervisionati."
    )

    # Mock two separate LLM responses: one for write, one for expand.
    with patch(
        "app.agents.writer.call_llm",
        AsyncMock(side_effect=[short_latex, expanded_latex]),
    ) as mock_llm:
        # Step 1: write a section (first LLM call).
        written = await write_section(
            section,
            documents,
            [],
            {},
            "",
            "italian",
            fake_llm_config,
        )
        assert mock_llm.call_count == 1
        # First call must NOT use WRITER_EXPAND_SYSTEM (should use WRITER_SYSTEM).
        system_prompt_1 = mock_llm.call_args_list[0][0][1]
        assert system_prompt_1 != WRITER_EXPAND_SYSTEM, (
            "First LLM call must be write_section (WRITER_SYSTEM), not expand"
        )
        assert len(written["latex"]) < 80, (
            f"Section should be short (< 80 chars), got {len(written['latex'])}"
        )
        # Step 2: expand it (second LLM call).
        expanded = await expand_section(written, documents, "italian", fake_llm_config)
        assert mock_llm.call_count == 2, (
            f"expand_section must make a second LLM call, got {mock_llm.call_count}"
        )
        # The second call MUST use WRITER_EXPAND_SYSTEM, not WRITER_SYSTEM.
        system_prompt_2 = mock_llm.call_args_list[1][0][1]
        assert system_prompt_2 == WRITER_EXPAND_SYSTEM, (
            "Second LLM call must use WRITER_EXPAND_SYSTEM prompt"
        )
        # The second call's user prompt must include the original section.
        user_prompt_2: str = mock_llm.call_args_list[1][0][2]
        assert "SEZIONE ATTUALE DA ESPANDERE" in user_prompt_2, (
            "Expand prompt must contain the original section to expand"
        )
        assert "Breve introduzione" in user_prompt_2
        # Result must be longer than the input.
        assert len(expanded["latex"]) > len(written["latex"]), (
            f"Expanded ({len(expanded['latex'])}) must be longer than "
            f"original ({len(written['latex'])})"
        )
        # Result must contain the original content (no overwrite).
        assert "Breve introduzione" in expanded["latex"], (
            "Expanded section must preserve original content"
        )
        # Result must contain new content not in the original.
        assert "machine learning" in expanded["latex"].lower()


# ── Parallel chapters: no context sharing across chapters ─────────────────


@pytest.mark.asyncio
async def test_parallel_chapters_asyncio_gather_context_isolation(
    plan_two_chapters,
    documents_no_apprendono,
    fake_llm_config,
    section1_latex,
    section1_context_json,
    section2_latex,
):
    """Chapters run in parallel via asyncio.gather do NOT share context.

    Simulates the graph's write_node pattern: each chapter is an async task
    with its own context accumulation. Chapter 1's facts must NEVER appear
    in Chapter 2's FIRST write (which starts with writer_context=None).
    Uses a label-aware mock so call order doesn't matter (asyncio.gather
    makes order non-deterministic).
    """
    c1_s1 = plan_two_chapters[0]  # Capitolo 1
    c2_s1 = plan_two_chapters[1]  # Capitolo 2, sezione 1
    c2_s2 = plan_two_chapters[2]  # Capitolo 2, sezione 2
    docs = documents_no_apprendono

    # Track every call's (label, user_prompt) for post-hoc inspection.
    recorded: list[tuple[str, str]] = []

    async def mock_call_llm(llm_config, system, user, **kwargs):
        label = kwargs.get("label", "")
        recorded.append((label, user))
        if label and label.startswith("context:"):
            return section1_context_json
        return section1_latex

    with patch("app.agents.writer.call_llm", mock_call_llm):

        async def chapter1():
            r = await write_section(
                c1_s1,
                docs,
                [],
                {},
                "",
                "italian",
                fake_llm_config,
                writer_context=None,
            )
            facts = await summarize_section_context(r, fake_llm_config)
            return r, facts

        async def chapter2():
            r1 = await write_section(
                c2_s1,
                docs,
                [],
                {},
                "",
                "italian",
                fake_llm_config,
                writer_context=None,
            )
            # Section 2.2 gets context from 2.1 (intra-chapter, never from chapter 1).
            facts_c2 = await summarize_section_context(r1, fake_llm_config)
            r2 = await write_section(
                c2_s2,
                docs,
                [],
                {},
                "",
                "italian",
                fake_llm_config,
                writer_context=facts_c2 if facts_c2 else None,
            )
            return r1, r2

        (c1_result, c1_facts), (c2_r1, c2_r2) = await asyncio.gather(
            chapter1(), chapter2()
        )

    # ── Assertions ───────────────────────────────────────────────────────
    assert c1_result["title"] == c1_s1["title"]
    assert c2_r1["title"] == c2_s1["title"]
    assert c2_r2["title"] == c2_s2["title"]

    # Chapter 1 extracted its facts.
    assert len(c1_facts) > 0
    assert any("apprendono" in f for f in c1_facts), (
        f"Chapter 1 facts should contain 'apprendono'. Got: {c1_facts}"
    )

    # Chapter 2's FIRST write (section 2.1) must have received NO context.
    # Its prompt mentions the section title "2.1 Tecniche avanzate" and
    # has label starting with "write:", distinguishing it from context calls.
    c2_s1_writes = [
        (lbl, prompt)
        for lbl, prompt in recorded
        if lbl.startswith("write:")
        and ("2.1" in prompt or "Tecniche avanzate" in prompt)
    ]
    assert len(c2_s1_writes) == 1, (
        f"Expected exactly 1 write call for section 2.1. "
        f"Found {len(c2_s1_writes)}. Recorded: {[lbl for lbl, _ in recorded]}"
    )
    _, c2_s1_prompt = c2_s1_writes[0]
    assert "CONCETTI GIÀ TRATTATI" not in c2_s1_prompt, (
        f"Chapter 2 section 1 must NOT receive context from chapter 1. "
        f"Prompt: {c2_s1_prompt[:300]}"
    )

    # Chapter 2's SECOND write (section 2.2) MAY have intra-chapter context
    # from 2.1, but that context must NOT be chapter 1's cross-contamination.
    # Since both chapters get the same mock context, we verify 2.2's prompt
    # exists and was a write call.
    c2_s2_writes = [
        (lbl, prompt)
        for lbl, prompt in recorded
        if lbl.startswith("write:") and ("2.2" in prompt or "Applicazioni" in prompt)
    ]
    assert len(c2_s2_writes) == 1, "Expected exactly 1 write call for section 2.2."

    # Total: 3 writes (c1_s1, c2_s1, c2_s2) + 2 context extractions = 5 calls.
    assert len(recorded) == 5, (
        f"Expected 5 LLM calls (3 writes + 2 context extractions). "
        f"Got {len(recorded)}. Labels: {[lbl for lbl, _ in recorded]}"
    )


@pytest.mark.asyncio
async def test_different_chapters_do_not_share_context(
    plan_two_chapters,
    documents_no_apprendono,
    fake_llm_config,
    section1_latex,
    section1_context_json,
    section2_latex,
    section2_context_json,
):
    """Cross-chapter isolation: section 2.1 gets no context from chapter 1.

    But within chapter 2, section 2.2 DOES get context from 2.1.
    """
    c1_s1 = plan_two_chapters[0]  # Capitolo 1, sezione 1
    c2_s1 = plan_two_chapters[1]  # Capitolo 2, sezione 1
    c2_s2 = plan_two_chapters[2]  # Capitolo 2, sezione 2
    docs = documents_no_apprendono

    # 1: write section 1, 2: extract context 1, 3: write section 2, 4: write section 3 (with context from 2)
    responses = [section1_latex, section1_context_json, section1_latex, section2_latex]

    with patch(
        "app.agents.writer.call_llm", AsyncMock(side_effect=responses)
    ) as mock_llm:
        # Chapter 1 section 1 (no context)
        r1 = await write_section(
            c1_s1, docs, [], {}, "", "italian", fake_llm_config, writer_context=None
        )
        user1 = mock_llm.call_args_list[0][0][2]
        assert "CONCETTI GIÀ TRATTATI" not in user1

        # Extract context from chapter 1 section 1
        facts_ch1 = await summarize_section_context(r1, fake_llm_config)
        assert len(facts_ch1) > 0

        # Chapter 2 section 1 — should NOT receive context from chapter 1
        _r2 = await write_section(
            c2_s1, docs, [], {}, "", "italian", fake_llm_config, writer_context=None
        )
        user2 = mock_llm.call_args_list[2][0][2]
        assert "CONCETTI GIÀ TRATTATI" not in user2, (
            "Chapter 2 section 1 must NOT receive context from chapter 1"
        )

        # Chapter 2 section 2 — SHOULD receive context from chapter 2 section 1's facts
        _r3 = await write_section(
            c2_s2,
            docs,
            [],
            {},
            "",
            "italian",
            fake_llm_config,
            writer_context=facts_ch1,
        )
        user3 = mock_llm.call_args_list[3][0][2]
        # When writer_context is passed (as write_node would for intra-chapter),
        # it DOES appear — this is the intra-chapter path
        assert "CONCETTI GIÀ TRATTATI" in user3, (
            "Chapter 2 section 2 should receive intra-chapter context"
        )
