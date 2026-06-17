"""Tests for prompt strings: existence, format, and .replace() behavior."""

import pytest

from app.agents.prompts import (
    ANALYZER_REDUCE_SYSTEM,
    ANALYZER_SYSTEM,
    JUDGE_REVISE_SYSTEM,
    JUDGE_SYSTEM,
    JUDGE_VISION_SYSTEM,
    OVERVIEW_SYSTEM,
    PLANNER_SYSTEM,
    REVIEWER_SYSTEM,
    SECTION_REFINE_SYSTEM,
    WRITER_CONTEXT_SUMMARIZE_SYSTEM,
    WRITER_EXPAND_SYSTEM,
    WRITER_KNOWLEDGE_INSTRUCTION,
    WRITER_NO_KNOWLEDGE_INSTRUCTION,
    WRITER_SYSTEM,
)

# ── All prompts exist and are non-empty ───────────────────────────────────

ALL_PROMPTS = [
    ("ANALYZER_SYSTEM", ANALYZER_SYSTEM),
    ("ANALYZER_REDUCE_SYSTEM", ANALYZER_REDUCE_SYSTEM),
    ("PLANNER_SYSTEM", PLANNER_SYSTEM),
    ("WRITER_SYSTEM", WRITER_SYSTEM),
    ("WRITER_EXPAND_SYSTEM", WRITER_EXPAND_SYSTEM),
    ("WRITER_CONTEXT_SUMMARIZE_SYSTEM", WRITER_CONTEXT_SUMMARIZE_SYSTEM),
    ("OVERVIEW_SYSTEM", OVERVIEW_SYSTEM),
    ("REVIEWER_SYSTEM", REVIEWER_SYSTEM),
    ("JUDGE_SYSTEM", JUDGE_SYSTEM),
    ("JUDGE_VISION_SYSTEM", JUDGE_VISION_SYSTEM),
    ("JUDGE_REVISE_SYSTEM", JUDGE_REVISE_SYSTEM),
    ("SECTION_REFINE_SYSTEM", SECTION_REFINE_SYSTEM),
]


@pytest.mark.parametrize("name, prompt", ALL_PROMPTS)
def test_prompt_is_non_empty(name, prompt):
    """Every prompt constant is a non-empty string."""
    assert isinstance(prompt, str), f"{name} is not a string"
    assert len(prompt.strip()) > 50, f"{name} is too short ({len(prompt)} chars)"


# ── WRITER_SYSTEM .replace() behavior ─────────────────────────────────────


def test_writer_system_has_knowledge_placeholder():
    """WRITER_SYSTEM contains the {knowledge_instruction} placeholder."""
    assert "{knowledge_instruction}" in WRITER_SYSTEM


def test_writer_system_replace_works():
    """replacing the placeholder injects the instruction."""
    result = WRITER_SYSTEM.replace("{knowledge_instruction}", "TEST_INSTRUCTION")
    assert "TEST_INSTRUCTION" in result
    assert "{knowledge_instruction}" not in result


def test_writer_system_replace_idempotent():
    """Multiple .replace() calls are idempotent."""
    once = WRITER_SYSTEM.replace("{knowledge_instruction}", "X")
    twice = once.replace("{knowledge_instruction}", "X")
    assert once == twice


def test_knowledge_instruction_distinct():
    """WRITER_KNOWLEDGE_INSTRUCTION and WRITER_NO_KNOWLEDGE_INSTRUCTION differ."""
    assert WRITER_KNOWLEDGE_INSTRUCTION != WRITER_NO_KNOWLEDGE_INSTRUCTION
    assert "NON inventare" in WRITER_NO_KNOWLEDGE_INSTRUCTION
    assert "INTEGRARE" in WRITER_KNOWLEDGE_INSTRUCTION


# ── Other prompts key phrases ─────────────────────────────────────────────


def test_writer_expand_has_rules():
    """WRITER_EXPAND_SYSTEM mentions key rules."""
    assert "Mantieni TUTTO il contenuto esistente" in WRITER_EXPAND_SYSTEM
    assert "NON cambiare la struttura" in WRITER_EXPAND_SYSTEM


def test_context_summarize_describes_json():
    """WRITER_CONTEXT_SUMMARIZE_SYSTEM asks for JSON array."""
    assert "array JSON" in WRITER_CONTEXT_SUMMARIZE_SYSTEM
    assert "3-5 fatti chiave" in WRITER_CONTEXT_SUMMARIZE_SYSTEM


def test_overview_asks_for_chapters():
    """OVERVIEW_SYSTEM expects chapters array."""
    assert "chapters" in OVERVIEW_SYSTEM
    assert "synopsis" in OVERVIEW_SYSTEM


def test_writer_has_anti_repetition_rule():
    """WRITER_SYSTEM instructs against repeating concepts."""
    assert (
        "NON ripetere definizioni" in WRITER_SYSTEM
        or "CONCETTI GIÀ TRATTATI" in WRITER_SYSTEM
    )


def test_writer_has_no_truncation_rule():
    """WRITER_SYSTEM tells the LLM not to truncate."""
    assert "Non accorciare" in WRITER_SYSTEM or "sezione SOSTANZIOSA" in WRITER_SYSTEM
