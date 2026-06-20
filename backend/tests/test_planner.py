"""Unit tests for planner.py: deterministic source-order sorting."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.planner import plan_document

# ── Mock plan object returned by call_llm_structured ───────────────────────


class _MockPlanSection:
    """Mimics a single section from the LLM's PlanSchema output."""

    def __init__(
        self,
        part_title: str = "Capitolo",
        title: str = "Sezione",
        order_index: int = 0,
        source_filenames: list[str] | None = None,
    ):
        self.part_title = part_title
        self.title = title
        self.order_index = order_index
        self.source_filenames = source_filenames or []
        self.outline: dict = {}


class _MockPlan:
    """Mimics the structured plan object returned by the LLM."""

    def __init__(self, title: str = "Test Doc", sections: list | None = None):
        self.title = title
        self.sections = sections or []


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deterministic_source_order_sorts_by_earliest_document():
    """Sections sort by the earliest source document, not the LLM's order_index."""

    # Analyses in user-chosen extraction order: A first, B second, C third.
    analyses = [
        {"filename": "doc_a.pdf", "summary": "A"},
        {"filename": "doc_b.pdf", "summary": "B"},
        {"filename": "doc_c.pdf", "summary": "C"},
    ]

    # LLM returns sections in random order (by order_index: 2, 1, 3).
    # Section referencing doc C should come LAST because doc C is last in extraction.
    # Section referencing doc B should come AFTER sections referencing doc A.
    mock_plan = _MockPlan(
        title="Test",
        sections=[
            _MockPlanSection(
                part_title="Chapter C",
                title="C Topic",
                order_index=2,
                source_filenames=["doc_c.pdf"],
            ),
            _MockPlanSection(
                part_title="Chapter A",
                title="A Intro",
                order_index=1,
                source_filenames=["doc_a.pdf"],
            ),
            _MockPlanSection(
                part_title="Chapter B",
                title="B Topic",
                order_index=3,
                source_filenames=["doc_b.pdf"],
            ),
        ],
    )

    with patch(
        "app.agents.planner.call_llm_structured",
        AsyncMock(return_value=mock_plan),
    ):
        title, plan = await plan_document(
            analyses=analyses,
            user_prompt="",
            language="italian",
            llm_config={"provider": "fake", "model": "test"},
            structure_hint="",
        )

    # Assert: sections are ordered by source document: A → B → C.
    assert len(plan) == 3
    assert plan[0]["title"] == "A Intro"
    assert plan[1]["title"] == "B Topic"
    assert plan[2]["title"] == "C Topic"

    # Assert: order_index has been rewritten to sequential.
    assert plan[0]["order_index"] == 0
    assert plan[1]["order_index"] == 1
    assert plan[2]["order_index"] == 2


@pytest.mark.asyncio
async def test_cross_referencing_section_uses_earliest_source():
    """A section referencing multiple documents anchors to the earliest."""

    analyses = [
        {"filename": "doc_a.pdf", "summary": "A"},
        {"filename": "doc_b.pdf", "summary": "B"},
        {"filename": "doc_c.pdf", "summary": "C"},
    ]

    mock_plan = _MockPlan(
        title="Test",
        sections=[
            _MockPlanSection(
                part_title="Ch 1",
                title="C-only section",
                order_index=0,
                source_filenames=["doc_c.pdf"],
            ),
            _MockPlanSection(
                part_title="Ch 1",
                title="A+B cross section",
                order_index=1,
                source_filenames=["doc_b.pdf", "doc_a.pdf"],
            ),
            _MockPlanSection(
                part_title="Ch 2",
                title="B-only section",
                order_index=2,
                source_filenames=["doc_b.pdf"],
            ),
        ],
    )

    with patch(
        "app.agents.planner.call_llm_structured",
        AsyncMock(return_value=mock_plan),
    ):
        title, plan = await plan_document(
            analyses=analyses,
            user_prompt="",
            language="italian",
            llm_config={"provider": "fake", "model": "test"},
            structure_hint="",
        )

    assert len(plan) == 3
    # A+B cross section references doc_a (index 0) → comes first.
    assert plan[0]["title"] == "A+B cross section"
    # B-only section references doc_b (index 1) → comes second.
    assert plan[1]["title"] == "B-only section"
    # C-only section references doc_c (index 2) → comes last.
    assert plan[2]["title"] == "C-only section"


@pytest.mark.asyncio
async def test_structure_hint_preserves_llm_order():
    """When structure_hint is present, the LLM's order_index is preserved."""

    analyses = [
        {"filename": "doc_a.pdf", "summary": "A"},
        {"filename": "doc_b.pdf", "summary": "B"},
    ]

    # LLM puts doc_b before doc_a (order_index: B=1, A=2).
    mock_plan = _MockPlan(
        title="Test",
        sections=[
            _MockPlanSection(
                part_title="Ch B",
                title="B First",
                order_index=1,
                source_filenames=["doc_b.pdf"],
            ),
            _MockPlanSection(
                part_title="Ch A",
                title="A Second",
                order_index=2,
                source_filenames=["doc_a.pdf"],
            ),
        ],
    )

    with patch(
        "app.agents.planner.call_llm_structured",
        AsyncMock(return_value=mock_plan),
    ):
        title, plan = await plan_document(
            analyses=analyses,
            user_prompt="",
            language="italian",
            llm_config={"provider": "fake", "model": "test"},
            structure_hint="Metti B prima di A",
        )

    assert len(plan) == 2
    # With structure_hint, LLM order is trusted: B first, A second.
    assert plan[0]["title"] == "B First"
    assert plan[1]["title"] == "A Second"

    # order_index still normalized to sequential.
    assert plan[0]["order_index"] == 0
    assert plan[1]["order_index"] == 1


@pytest.mark.asyncio
async def test_same_source_multiple_sections_preserve_llm_order():
    """Within the same source document, the LLM's order_index is the tiebreak."""

    analyses = [
        {"filename": "doc_a.pdf", "summary": "A"},
    ]

    mock_plan = _MockPlan(
        title="Test",
        sections=[
            _MockPlanSection(
                part_title="Ch 1",
                title="A Third",
                order_index=3,
                source_filenames=["doc_a.pdf"],
            ),
            _MockPlanSection(
                part_title="Ch 1",
                title="A First",
                order_index=1,
                source_filenames=["doc_a.pdf"],
            ),
            _MockPlanSection(
                part_title="Ch 1",
                title="A Second",
                order_index=2,
                source_filenames=["doc_a.pdf"],
            ),
        ],
    )

    with patch(
        "app.agents.planner.call_llm_structured",
        AsyncMock(return_value=mock_plan),
    ):
        title, plan = await plan_document(
            analyses=analyses,
            user_prompt="",
            language="italian",
            llm_config={"provider": "fake", "model": "test"},
            structure_hint="",
        )

    assert len(plan) == 3
    # All from same source → tied on source_priority → LLM order_index used.
    assert plan[0]["title"] == "A First"
    assert plan[1]["title"] == "A Second"
    assert plan[2]["title"] == "A Third"


@pytest.mark.asyncio
async def test_section_without_source_filenames_sorts_last():
    """A section with no source_filenames sorts after everything else."""

    analyses = [
        {"filename": "doc_a.pdf", "summary": "A"},
    ]

    mock_plan = _MockPlan(
        title="Test",
        sections=[
            _MockPlanSection(
                part_title="Ch 1",
                title="A Section",
                order_index=0,
                source_filenames=["doc_a.pdf"],
            ),
            _MockPlanSection(
                part_title="Ch 2",
                title="Orphan Section",
                order_index=1,
                source_filenames=[],
            ),
        ],
    )

    with patch(
        "app.agents.planner.call_llm_structured",
        AsyncMock(return_value=mock_plan),
    ):
        title, plan = await plan_document(
            analyses=analyses,
            user_prompt="",
            language="italian",
            llm_config={"provider": "fake", "model": "test"},
            structure_hint="",
        )

    assert len(plan) == 2
    assert plan[0]["title"] == "A Section"
    assert plan[1]["title"] == "Orphan Section"


@pytest.mark.asyncio
async def test_unknown_filenames_sorted_by_order_index():
    """source_filenames that don't match any analysis → sort by order_index."""

    analyses = [
        {"filename": "doc_a.pdf", "summary": "A"},
    ]

    mock_plan = _MockPlan(
        title="Test",
        sections=[
            _MockPlanSection(
                part_title="Ch 1",
                title="Unknown B",
                order_index=2,
                source_filenames=["unknown_b.pdf"],
            ),
            _MockPlanSection(
                part_title="Ch 1",
                title="Unknown A",
                order_index=1,
                source_filenames=["unknown_a.pdf"],
            ),
        ],
    )

    with patch(
        "app.agents.planner.call_llm_structured",
        AsyncMock(return_value=mock_plan),
    ):
        title, plan = await plan_document(
            analyses=analyses,
            user_prompt="",
            language="italian",
            llm_config={"provider": "fake", "model": "test"},
            structure_hint="",
        )

    assert len(plan) == 2
    # Both have inf priority → sorted by order_index: 1 before 2.
    assert plan[0]["title"] == "Unknown A"
    assert plan[1]["title"] == "Unknown B"
