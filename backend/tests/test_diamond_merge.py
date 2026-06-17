"""Tests for the diamond parallel pattern: merge_node pass-through and
state aggregation from the three fan-out nodes (overview, coherence, citations).

All LLM calls are mocked — no network dependencies.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph import citation_node, coherence_node, merge_node, overview_node
from app.agents.state import GraphState
from app.core.config import settings as _cfg


def _base_state(**overrides) -> GraphState:
    """Build a minimal GraphState dict with required keys for the diamond nodes."""
    state: GraphState = {
        "documents": [
            {"filename": "a.pdf", "full_text": "test", "mandatory_figures": []},
            {"filename": "b.pdf", "full_text": "test", "mandatory_figures": []},
        ],
        "analyses": [],
        "llm_config": {"provider": "fake", "model": "test"},
        "plan": [],
        "sections": [
            {
                "title": "1.1 Intro",
                "part_title": "Capitolo 1",
                "order_index": 0,
                "latex": r"\section{Intro} Test.",
                "outline": {"punti": ["A"]},
                "source_filenames": ["a.pdf"],
            },
            {
                "title": "2.1 Avanzato",
                "part_title": "Capitolo 2",
                "order_index": 1,
                "latex": r"\section{Avanzato} Test.",
                "outline": {"punti": ["B"]},
                "source_filenames": ["b.pdf"],
            },
            {
                "title": "2.2 Approfondimento",
                "part_title": "Capitolo 2",
                "order_index": 2,
                "latex": r"\section{Approfondimento} Test.",
                "outline": {"punti": ["C"]},
                "source_filenames": ["b.pdf"],
            },
        ],
        "references_pool": [],
        "final_latex": "",
        "good_latex": "",
        "good_pdf": None,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


# ── merge_node: pass-through behaviour ────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_node_returns_empty_dict():
    """merge_node is a pure pass-through — it returns {} regardless of state."""
    state = _base_state()
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    result = await merge_node(state)
    assert result == {}, "merge_node must return empty dict (pass-through)"

    # Progress was emitted.
    assert len(progress_events) == 1
    assert progress_events[0]["stage"] == "merge"


@pytest.mark.asyncio
async def test_merge_node_reports_coherence_score():
    """When coherence_score is set in state, the merge progress reports it."""
    state = _base_state(coherence_score=85)
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    await merge_node(state)
    msg = progress_events[0]["message"]
    assert "coerenza 85/100" in msg


@pytest.mark.asyncio
async def test_merge_node_reports_citation_issues():
    """When citation_issues are present, the merge progress reports the count."""
    state = _base_state(
        citation_issues=[
            "Chiave sconosciuta: bogus",
            "Fonte utente non citata: he2016",
        ],
        citation_report="2 problemi",
    )
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    await merge_node(state)
    msg = progress_events[0]["message"]
    assert "2 problemi citazioni" in msg


@pytest.mark.asyncio
async def test_merge_node_reports_coherence_issues():
    """When coherence_issues are present, the merge progress reports the count."""
    state = _base_state(
        coherence_issues=[
            "Contraddizione tra Cap 1 e Cap 3",
            "Terminologia incoerente",
        ],
        coherence_score=55,
    )
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    await merge_node(state)
    msg = progress_events[0]["message"]
    assert "2 problemi coerenza" in msg


@pytest.mark.asyncio
async def test_merge_node_all_three_combined():
    """All three parallel results present → merge reports all of them."""
    state = _base_state(
        coherence_score=70,
        coherence_issues=["Ripetizione: Cap 1 e Cap 2 stessa definizione"],
        citation_issues=["Fonte utente non citata"],
        citation_report="1 problema",
        overview_latex=r"\chapter*{Panoramica}...",
    )
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    await merge_node(state)
    msg = progress_events[0]["message"]
    assert "coerenza 70/100" in msg
    assert "1 problemi citazioni" in msg
    assert "1 problemi coerenza" in msg


@pytest.mark.asyncio
async def test_merge_node_none_score_omitted():
    """When coherence_score is None (not set), it's not reported."""
    state = _base_state()
    # coherence_score not set → state.get returns None
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    await merge_node(state)
    msg = progress_events[0]["message"]
    assert "coerenza" not in msg
    assert msg == "Verifiche completate"  # empty parts → no suffix


# ── Non-overlapping state keys across the three parallel nodes ────────────


@pytest.mark.asyncio
async def test_parallel_nodes_keys_disjoint():
    """overview_node, coherence_node, citation_node produce disjoint state keys.

    This is critical for the diamond pattern: overlapping keys would cause
    race conditions when LangGraph merges parallel node outputs.
    """
    from app.agents.schemas import CitationAuditSchema, CoherenceSchema

    state = _base_state(
        established_facts={
            "Capitolo 1": ["Fatto 1A", "Fatto 1B"],
            "Capitolo 2": ["Fatto 2A"],
        },
    )
    _coherence_verdict = CoherenceSchema(
        approved=True, score=90, issues=[], summary="Ok"
    )
    _citation_verdict = CitationAuditSchema(
        approved=True, score=100, issues=[], summary="Ok"
    )

    # Mock all LLM calls.
    with (
        patch("app.agents.graph.call_llm_structured") as mock_structured,
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(
                return_value={
                    "approved": True,
                    "score": 90,
                    "issues": [],
                    "summary": "Ok",
                }
            ),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(
                return_value={
                    "approved": True,
                    "score": 100,
                    "uncited_user_sources": [],
                    "unknown_citations": [],
                    "issues": [],
                    "summary": "Ok",
                }
            ),
        ),
    ):
        mock_structured.return_value = type(
            "V",
            (),
            {
                "chapters": [type("C", (), {"part_title": "Cap 1", "synopsis": "Syn"})],
            },
        )()

        o_result = await overview_node(state)
        c_result = await coherence_node(state)
        a_result = await citation_node(state)

    # Check which keys each node writes to.
    o_keys = set(o_result.keys())
    c_keys = set(c_result.keys())
    a_keys = set(a_result.keys())

    # overview_node writes overview_latex.
    assert o_keys == {"overview_latex"} or o_keys == set(), (
        f"overview_node keys: {o_keys}"
    )
    # coherence_node writes coherence_issues + coherence_score.
    assert c_keys == {"coherence_issues", "coherence_score"}, (
        f"coherence_node keys: {c_keys}"
    )
    # citation_node writes citation_issues + citation_report.
    assert a_keys == {"citation_issues", "citation_report"}, (
        f"citation_node keys: {a_keys}"
    )

    # Verify all key sets are pairwise disjoint.
    overlap_oc = o_keys & c_keys
    overlap_oa = o_keys & a_keys
    overlap_ca = c_keys & a_keys
    assert not overlap_oc, f"overview and coherence share keys: {overlap_oc}"
    assert not overlap_oa, f"overview and citations share keys: {overlap_oa}"
    assert not overlap_ca, f"coherence and citations share keys: {overlap_ca}"


# ── Simulated full diamond fan-out + fan-in ───────────────────────────────


@pytest.mark.asyncio
async def test_diamond_fan_out_fan_in_state_aggregation():
    """Simulate write → fan-out → fan-in: all parallel results merge correctly.

    This mimics what LangGraph does in one super-step: run the three fan-out
    nodes (overview, coherence, citations) and verify that merging their
    results produces a state the merge_node can consume correctly.
    """

    state = _base_state(
        established_facts={
            "Capitolo 1": ["Fatto 1"],
            "Capitolo 2": ["Fatto 2"],
        },
    )
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    with (
        patch("app.agents.graph.call_llm_structured") as mock_structured,
        patch(
            "app.agents.graph.check_coherence",
            AsyncMock(
                return_value={
                    "approved": False,
                    "score": 45,
                    "issues": ["Contraddizione rilevata"],
                    "summary": "Problema",
                }
            ),
        ),
        patch(
            "app.agents.graph.audit_citations",
            AsyncMock(
                return_value={
                    "approved": True,
                    "score": 100,
                    "uncited_user_sources": [],
                    "unknown_citations": [],
                    "issues": [],
                    "summary": "Ok",
                }
            ),
        ),
    ):
        # Mock overview response.
        mock_structured.return_value = type(
            "V",
            (),
            {
                "chapters": [
                    type(
                        "C", (), {"part_title": "Capitolo 1", "synopsis": "Sintesi 1"}
                    ),
                    type(
                        "C", (), {"part_title": "Capitolo 2", "synopsis": "Sintesi 2"}
                    ),
                ],
            },
        )()

        # Run all three in parallel (same as graph's super-step).
        o_result, c_result, a_result = await asyncio.gather(
            overview_node(state),
            coherence_node(state),
            citation_node(state),
        )

    # Simulate LangGraph state merging: all results applied to state.
    merged_state = {**state, **o_result, **c_result, **a_result}

    # All three nodes produced results.
    assert "overview_latex" in merged_state, "overview should have set overview_latex"
    assert merged_state["coherence_score"] == 45
    assert merged_state["coherence_issues"] == ["Contraddizione rilevata"]
    assert merged_state["citation_report"] == "Ok"
    assert merged_state["citation_issues"] == []

    # Clear progress events before merge_node.
    progress_events.clear()

    # Now run merge_node with the aggregated state.
    merge_result = await merge_node(merged_state)

    assert merge_result == {}, "merge_node must be pass-through"
    assert len(progress_events) == 1
    msg = progress_events[0]["message"]
    assert "coerenza 45/100" in msg, (
        f"Merge should report coherence score 45. Got: {msg}"
    )
    assert "1 problemi coerenza" in msg, (
        f"Merge should report 1 coherence issue. Got: {msg}"
    )


# ── Disabled nodes still work with the diamond pattern ────────────────────


@pytest.mark.asyncio
async def test_coherence_disabled_node_returns_empty():
    """When coherence_enabled=False, coherence_node returns {} gracefully."""
    state = _base_state(
        established_facts={
            "Capitolo 1": ["Fatto 1"],
            "Capitolo 2": ["Fatto 2"],
        },
    )
    with patch.object(_cfg, "coherence_enabled", False):
        result = await coherence_node(state)

    assert result == {}, "Disabled coherence_node must return {}"


@pytest.mark.asyncio
async def test_citations_disabled_node_returns_empty():
    """When citations_enabled=False, citation_node returns {} gracefully."""
    state = _base_state()
    with patch.object(_cfg, "citations_enabled", False):
        result = await citation_node(state)

    assert result == {}, "Disabled citation_node must return {}"


@pytest.mark.asyncio
async def test_merge_works_with_disabled_parallel_nodes():
    """Even when all parallel nodes return {} (disabled), merge still works."""
    state = _base_state()
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    # Simulate all three returning {} (disabled or no-op).
    merged_state = {
        **state,
        **{},  # overview
        **{},  # coherence
        **{},  # citations
    }

    result = await merge_node(merged_state)
    assert result == {}
    assert len(progress_events) == 1
    assert progress_events[0]["message"] == "Verifiche completate"


# ── Disabled nodes: ensure LLM is NEVER called ────────────────────────────


@pytest.mark.asyncio
async def test_coherence_disabled_skips_llm_call():
    """When coherence_enabled=False, check_coherence is NEVER called.

    The node must short-circuit before reaching the LLM, regardless of
    whether the state has valid input (established_facts with >= 2 chapters).
    """
    state = _base_state(
        established_facts={
            "Capitolo 1": ["Fatto 1A", "Fatto 1B"],
            "Capitolo 2": ["Fatto 2A"],
            "Capitolo 3": ["Fatto 3A", "Fatto 3B"],
        },
    )

    with (
        patch.object(_cfg, "coherence_enabled", False),
        patch("app.agents.graph.check_coherence") as mock_check,
    ):
        result = await coherence_node(state)

    assert result == {}
    mock_check.assert_not_called()


@pytest.mark.asyncio
async def test_citations_disabled_skips_llm_call():
    """When citations_enabled=False, audit_citations is NEVER called.

    The node must short-circuit before reaching the LLM, regardless of
    whether the state has valid input (sections + pool + user_sources).
    """
    state = _base_state(
        references_pool=[
            {
                "key": "he2016",
                "authors": "He",
                "title": "Deep Residual",
                "year": "2016",
            },
        ],
        user_sources=[
            {
                "authors": "Vaswani",
                "title": "Attention",
                "year": "2017",
                "venue": "NIPS",
            },
        ],
    )

    with (
        patch.object(_cfg, "citations_enabled", False),
        patch("app.agents.graph.audit_citations") as mock_audit,
    ):
        result = await citation_node(state)

    assert result == {}
    mock_audit.assert_not_called()


# ── Disabled nodes: no progress events emitted ────────────────────────────


@pytest.mark.asyncio
async def test_coherence_disabled_emits_no_progress():
    """Disabled coherence_node must NOT emit any progress event."""
    state = _base_state(
        established_facts={
            "Capitolo 1": ["Fatto 1"],
            "Capitolo 2": ["Fatto 2"],
        },
    )
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    with patch.object(_cfg, "coherence_enabled", False):
        result = await coherence_node(state)

    assert result == {}
    assert len(progress_events) == 0, (
        f"Disabled coherence_node must emit no progress, got {progress_events}"
    )


@pytest.mark.asyncio
async def test_citations_disabled_emits_no_progress():
    """Disabled citation_node must NOT emit any progress event."""
    state = _base_state(
        references_pool=[
            {"key": "he2016", "authors": "He", "title": "DR", "year": "2016"},
        ],
    )
    progress_events: list[dict] = []

    async def record(event):
        progress_events.append(event)

    state["progress"] = record

    with patch.object(_cfg, "citations_enabled", False):
        result = await citation_node(state)

    assert result == {}
    assert len(progress_events) == 0, (
        f"Disabled citation_node must emit no progress, got {progress_events}"
    )


# ── Disabled nodes: no side effects on state keys ─────────────────────────


@pytest.mark.asyncio
async def test_coherence_disabled_leaves_state_keys_untouched():
    """coherence_node returns {} → no coherence keys appear in result."""
    state = _base_state(
        established_facts={
            "Capitolo 1": ["Fatto 1"],
            "Capitolo 2": ["Fatto 2"],
        },
    )

    with patch.object(_cfg, "coherence_enabled", False):
        result = await coherence_node(state)

    assert result == {}
    assert "coherence_score" not in result
    assert "coherence_issues" not in result


@pytest.mark.asyncio
async def test_citations_disabled_leaves_state_keys_untouched():
    """citation_node returns {} → no citation keys appear in result."""
    state = _base_state(
        references_pool=[
            {"key": "he2016", "authors": "He", "title": "DR", "year": "2016"},
        ],
        user_sources=[
            {
                "authors": "Vaswani",
                "title": "Attention",
                "year": "2017",
                "venue": "NIPS",
            },
        ],
    )

    with patch.object(_cfg, "citations_enabled", False):
        result = await citation_node(state)

    assert result == {}
    assert "citation_issues" not in result
    assert "citation_report" not in result
