"""Integration tests for the Web Agent LangGraph flow.

Covers:
- Pure LLM mode (planner -> fetcher -> evaluator -> end)
- Hybrid mode (search adapters seed URLs, skip planner)
- Routing logic (_after_start, _after_evaluator)
- Error handling, max iterations, empty URLs, adapter exceptions.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.web_agent import (
    EvaluationResult,
    PlannedUrls,
    SearchResult,
    _after_evaluator,
    _after_start,
    build_web_agent_graph,
    evaluator_node,
    fetcher_node,
    planner_node,
    run_web_agent,
)
from app.services.web_search import _build_search_adapters

LLM = {"provider": "fake", "model": "test"}


# ── Smart mock for call_llm_structured that returns the right type ─────────


async def _llm_mock(*args, **kwargs):
    """Return EvaluationResult or PlannedUrls based on the label kwarg."""
    label = kwargs.get("label", "")
    if "evaluator" in label:
        return EvaluationResult(
            snippets=[
                {
                    "title": "Test Page",
                    "url": "https://example.com/test",
                    "content": "Extracted content from the test page.",
                },
            ],
            reasoning="Good enough.",
            is_satisfied=True,
            suggested_next_urls=[],
        )
    # planner or fallback
    return PlannedUrls(
        urls=["https://example.com/page1", "https://example.com/page2"],
        reasoning="These URLs look relevant.",
    )


# ── Routing unit tests ────────────────────────────────────────────────────


def test_after_start_with_seed_urls():
    result = _after_start({"current_urls": ["https://example.com"]})
    assert result == "fetcher"


def test_after_start_without_seed_urls():
    result = _after_start({"current_urls": []})
    assert result == "planner"


def test_after_evaluator_satisfied():
    result = _after_evaluator(
        {"is_complete": True, "iteration": 1, "max_iterations": 3}
    )
    assert result == "__end__"


def test_after_evaluator_max_iterations():
    result = _after_evaluator(
        {"is_complete": False, "iteration": 3, "max_iterations": 3}
    )
    assert result == "__end__"


def test_after_evaluator_continue():
    result = _after_evaluator(
        {"is_complete": False, "iteration": 1, "max_iterations": 3}
    )
    assert result == "planner"


def test_after_evaluator_iteration_zero():
    result = _after_evaluator(
        {"is_complete": False, "iteration": 0, "max_iterations": 3}
    )
    assert result == "planner"


# ── planner_node tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_planner_generates_urls():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=PlannedUrls(
                urls=["https://example.com/page1", "https://example.com/page2"],
                reasoning="These pages look relevant.",
            )
        ),
    ):
        result = await planner_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "visited_urls": [],
                "collected_results": [],
            }
        )

    assert result["current_urls"] == [
        "https://example.com/page1",
        "https://example.com/page2",
    ]
    assert "These pages look relevant" in result["planner_reasoning"]


@pytest.mark.asyncio
async def test_planner_filters_visited_urls():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=PlannedUrls(
                urls=["https://example.com/old", "https://example.com/new"],
                reasoning="One old, one new.",
            )
        ),
    ):
        result = await planner_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "visited_urls": ["https://example.com/old"],
                "collected_results": [],
            }
        )

    assert result["current_urls"] == ["https://example.com/new"]


@pytest.mark.asyncio
async def test_planner_fallback_on_error():
    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=RuntimeError("structured failed")),
        ),
        patch(
            "app.agents.web_agent.call_llm",
            AsyncMock(return_value="No useful URLs found."),
        ),
    ):
        result = await planner_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "visited_urls": [],
                "collected_results": [],
            }
        )

    assert result["current_urls"] == []
    assert "No useful URLs found" in result["planner_reasoning"]


@pytest.mark.asyncio
async def test_planner_caps_at_three_urls():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=PlannedUrls(
                urls=[f"https://example.com/page{i}" for i in range(10)],
                reasoning="Lots of URLs.",
            )
        ),
    ):
        result = await planner_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "visited_urls": [],
                "collected_results": [],
            }
        )

    assert len(result["current_urls"]) == 3


@pytest.mark.asyncio
async def test_planner_sees_collected_titles():
    collected = [
        SearchResult(
            title="Intro to ML",
            url="https://example.com/ml",
            snippet="Machine learning is...",
            content="Full content here.",
        ),
    ]
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(return_value=PlannedUrls(urls=[], reasoning="Already covered.")),
    ) as mock_structured:
        await planner_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "visited_urls": [],
                "collected_results": collected,
            }
        )

    call_args = mock_structured.call_args
    user_prompt = call_args[0][2]
    assert "Intro to ML" in user_prompt


# ── fetcher_node tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetcher_downloads_urls():
    with patch(
        "app.agents.web_agent._fetch_url",
        AsyncMock(side_effect=lambda u: (u, f"Content from {u}")),
    ):
        result = await fetcher_node(
            {
                "current_urls": ["https://a.com", "https://b.com"],
                "visited_urls": [],
                "iteration": 0,
            }
        )

    assert result["scraped_content"] == {
        "https://a.com": "Content from https://a.com",
        "https://b.com": "Content from https://b.com",
    }
    assert "https://a.com" in result["visited_urls"]
    assert "https://b.com" in result["visited_urls"]
    assert result["iteration"] == 1


@pytest.mark.asyncio
async def test_fetcher_handles_failed_fetch():
    with patch(
        "app.agents.web_agent._fetch_url",
        AsyncMock(
            side_effect=lambda u: (
                u,
                "" if "fail" in u else f"Content from {u}",
            )
        ),
    ):
        result = await fetcher_node(
            {
                "current_urls": ["https://ok.com", "https://fail.com"],
                "visited_urls": [],
                "iteration": 0,
            }
        )

    assert "https://ok.com" in result["scraped_content"]
    assert "https://fail.com" not in result["scraped_content"]
    assert "https://ok.com" in result["visited_urls"]
    assert "https://fail.com" in result["visited_urls"]


@pytest.mark.asyncio
async def test_fetcher_empty_urls_noop():
    result = await fetcher_node(
        {
            "current_urls": [],
            "visited_urls": ["already"],
            "iteration": 2,
        }
    )

    assert result["scraped_content"] == {}
    assert result["visited_urls"] == ["already"]
    assert result["iteration"] == 3


@pytest.mark.asyncio
async def test_fetcher_dedup_visited():
    result = await fetcher_node(
        {
            "current_urls": ["https://new.com"],
            "visited_urls": ["https://new.com"],
            "iteration": 0,
        }
    )

    assert result["visited_urls"].count("https://new.com") == 1


# ── evaluator_node tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluator_extracts_snippets():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=EvaluationResult(
                snippets=[
                    {
                        "title": "ML Overview",
                        "url": "https://example.com/ml",
                        "content": "Machine learning is a field of AI.",
                    },
                ],
                reasoning="Found a good overview.",
                is_satisfied=True,
                suggested_next_urls=[],
            )
        ),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {
                    "https://example.com/ml": "Machine learning is a field of AI.",
                },
                "collected_results": [],
            }
        )

    assert result["is_complete"] is True
    assert len(result["collected_results"]) == 1
    assert result["collected_results"][0].title == "ML Overview"


@pytest.mark.asyncio
async def test_evaluator_not_satisfied():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=EvaluationResult(
                snippets=[
                    {
                        "title": "Partial info",
                        "url": "https://example.com/partial",
                        "content": "Some partial content.",
                    },
                ],
                reasoning="Need more specialized sources.",
                is_satisfied=False,
                suggested_next_urls=["https://example.com/deep"],
            )
        ),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {
                    "https://example.com/partial": "Some partial content.",
                },
                "collected_results": [],
            }
        )

    assert result["is_complete"] is False
    assert result["suggested_next_urls"] == ["https://example.com/deep"]


@pytest.mark.asyncio
async def test_evaluator_error_fallback():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(side_effect=RuntimeError("evaluator crash")),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {"https://x.com": "content"},
                "collected_results": [],
            }
        )

    assert result["is_complete"] is True
    assert result["collected_results"] == []
    assert result["suggested_next_urls"] == []


@pytest.mark.asyncio
async def test_evaluator_merges_previous_results():
    existing = [
        SearchResult(
            title="Previous",
            url="https://old.com",
            snippet="Old content.",
            content="Old full content.",
        ),
    ]
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=EvaluationResult(
                snippets=[
                    {
                        "title": "New",
                        "url": "https://new.com",
                        "content": "New content.",
                    },
                ],
                reasoning="Added one.",
                is_satisfied=True,
                suggested_next_urls=[],
            )
        ),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {"https://new.com": "New content."},
                "collected_results": existing,
            }
        )

    assert len(result["collected_results"]) == 2
    assert result["collected_results"][0].title == "Previous"
    assert result["collected_results"][1].title == "New"


@pytest.mark.asyncio
async def test_evaluator_skips_invalid_snippets():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=EvaluationResult(
                snippets=[
                    {"title": "", "url": "x", "content": "x"},
                    {"title": "Good", "url": "x", "content": ""},
                    {
                        "title": "Valid",
                        "url": "https://valid.com",
                        "content": "Valid content.",
                    },
                ],
                reasoning="Test.",
                is_satisfied=True,
                suggested_next_urls=[],
            )
        ),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {},
                "collected_results": [],
            }
        )

    assert len(result["collected_results"]) == 1
    assert result["collected_results"][0].title == "Valid"


# ── run_web_agent — pure LLM mode ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_web_agent_pure_llm_one_round():
    """Pure LLM: planner → fetcher → evaluator (satisfied) → end."""
    with (
        patch(
            "app.agents.web_agent._fetch_url",
            AsyncMock(side_effect=lambda u: (u, f"Content from {u}")),
        ),
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=_llm_mock),
        ),
    ):
        results = await run_web_agent(
            query="machine learning",
            llm_config=LLM,
            max_iterations=3,
        )

    assert len(results) >= 1
    assert isinstance(results[0], SearchResult)


@pytest.mark.asyncio
async def test_run_web_agent_no_adapters_no_urls():
    """Pure LLM with planner returning empty URLs returns empty results."""

    async def empty_planner(*args, **kwargs):
        label = kwargs.get("label", "")
        if "evaluator" in label:
            return EvaluationResult(
                snippets=[],
                reasoning="Nothing to evaluate.",
                is_satisfied=True,
                suggested_next_urls=[],
            )
        return PlannedUrls(urls=[], reasoning="No results found.")

    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(side_effect=empty_planner),
    ):
        results = await run_web_agent(
            query="machine learning",
            llm_config=LLM,
            max_iterations=1,
        )

    assert results == []


# ── run_web_agent — hybrid mode with search adapters ──────────────────────


@pytest.mark.asyncio
async def test_run_web_agent_hybrid_with_adapters():
    """Hybrid: search adapters provide seed results + URLs to fetch."""
    mock_adapter = AsyncMock()
    mock_adapter.search = AsyncMock(
        return_value=[
            SearchResult(
                title="Wikipedia Article",
                url="https://en.wikipedia.org/wiki/Test",
                snippet="A test article.",
                content="Full Wikipedia content.",
            ),
            SearchResult(
                title="External Link",
                url="https://example.com/deep",
                snippet="",
                content="",
            ),
        ]
    )

    with (
        patch(
            "app.agents.web_agent._fetch_url",
            AsyncMock(return_value=("https://example.com/deep", "Deep dive content.")),
        ),
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=_llm_mock),
        ),
    ):
        results = await run_web_agent(
            query="test topic",
            llm_config=LLM,
            max_iterations=3,
            search_adapters=[mock_adapter],
        )

    # Content-rich result from adapter + fetched + evaluator snippet(s)
    assert len(results) >= 2
    titles = {r.title for r in results}
    assert "Wikipedia Article" in titles


@pytest.mark.asyncio
async def test_run_web_agent_hybrid_skips_planner():
    """Hybrid: seed URLs → skips planner → fetcher → evaluator."""
    mock_adapter = AsyncMock()
    mock_adapter.search = AsyncMock(
        return_value=[
            SearchResult(
                title="Some Page",
                url="https://example.com/page",
                snippet="",
                content="",
            ),
        ]
    )

    planner_called = False

    async def track_planner(state):
        nonlocal planner_called
        planner_called = True
        return {
            "current_urls": [],
            "planner_reasoning": "Should not be called.",
        }

    with (
        patch(
            "app.agents.web_agent._fetch_url",
            AsyncMock(return_value=("https://example.com/page", "Fetched content.")),
        ),
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=_llm_mock),
        ),
        patch(
            "app.agents.web_agent.planner_node",
            AsyncMock(side_effect=track_planner),
        ),
    ):
        await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=3,
            search_adapters=[mock_adapter],
        )

    assert not planner_called, (
        "Planner must not be called when seed URLs skip to fetcher"
    )


@pytest.mark.asyncio
async def test_run_web_agent_adapter_exception_handled():
    """When one adapter fails, the other still contributes."""
    mock_bad = AsyncMock()
    mock_bad.search = AsyncMock(side_effect=RuntimeError("network error"))
    mock_good = AsyncMock()
    mock_good.search = AsyncMock(
        return_value=[
            SearchResult(
                title="Good result",
                url="https://good.com",
                snippet="Nice.",
                content="Good content.",
            ),
        ]
    )

    async def evaluator_only(*args, **kwargs):
        label = kwargs.get("label", "")
        if "evaluator" in label:
            return EvaluationResult(
                snippets=[],
                reasoning="Already have enough.",
                is_satisfied=True,
                suggested_next_urls=[],
            )
        return PlannedUrls(urls=[], reasoning="Not needed.")

    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(side_effect=evaluator_only),
    ):
        results = await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=1,
            search_adapters=[mock_bad, mock_good],
        )

    assert any(r.title == "Good result" for r in results)


@pytest.mark.asyncio
async def test_run_web_agent_max_iterations_stops():
    """Max iterations caps the loop even when evaluator is never satisfied."""
    mock_adapter = AsyncMock()
    mock_adapter.search = AsyncMock(
        return_value=[
            SearchResult(
                title="Seed",
                url="https://seed.com",
                snippet="",
                content="",
            ),
        ]
    )

    call_count = 0

    async def never_satisfied(*args, **kwargs):
        nonlocal call_count
        label = kwargs.get("label", "")
        if "evaluator" in label:
            call_count += 1
            return EvaluationResult(
                snippets=[
                    {
                        "title": f"Iter {call_count}",
                        "url": f"https://iter{call_count}.com",
                        "content": f"Content {call_count}.",
                    },
                ],
                reasoning="Need more.",
                is_satisfied=False,
                suggested_next_urls=[f"https://iter{call_count + 1}.com"],
            )
        return PlannedUrls(
            urls=[f"https://plan{call_count}.com"],
            reasoning="Planner step.",
        )

    with (
        patch(
            "app.agents.web_agent._fetch_url",
            AsyncMock(side_effect=lambda u: (u, f"Content from {u}")),
        ),
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=never_satisfied),
        ),
    ):
        results = await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=2,
            search_adapters=[mock_adapter],
        )

    # 2 iterations max: seed fetcher→eval1 + planner→fetcher→eval2 = 2 eval calls
    assert call_count <= 3
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_run_web_agent_no_search_adapters_works():
    """When search_adapters is None, the pure LLM path still works."""
    with (
        patch(
            "app.agents.web_agent._fetch_url",
            AsyncMock(side_effect=lambda u: (u, f"Content from {u}")),
        ),
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=_llm_mock),
        ),
    ):
        results = await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=1,
            search_adapters=None,
        )

    assert isinstance(results, list)


# ── build_web_agent_graph ─────────────────────────────────────────────────


def test_build_graph_returns_compiled_graph():
    graph = build_web_agent_graph()
    assert graph is not None
    assert hasattr(graph, "ainvoke")


# ── _build_search_adapters — API key resolution ──────────────────────────


def test_build_search_adapters_no_search_tools():
    """Returns None when search_tools is empty."""
    result = _build_search_adapters({})
    assert result is None


def test_build_search_adapters_resolves_api_key():
    """Injects api_key from resolved_tools into the matching search_tool entry."""
    resolved = [
        {"tool_type": "tavily", "api_key": "tvly-secret"},
        {"tool_type": "wikipedia", "api_key": ""},
    ]
    params = {"search_tools": [{"tool_type": "tavily"}]}
    adapters = _build_search_adapters(params, resolved)
    assert adapters is not None
    assert len(adapters) == 1
    assert adapters[0].api_key == "tvly-secret"


def test_build_search_adapters_skips_when_has_key():
    """Does NOT override an already-present api_key."""
    resolved = [{"tool_type": "tavily", "api_key": "from-db"}]
    params = {"search_tools": [{"tool_type": "tavily", "api_key": "explicit"}]}
    adapters = _build_search_adapters(params, resolved)
    assert adapters is not None
    assert adapters[0].api_key == "explicit"


def test_build_search_adapters_multiple_tools():
    """Resolves keys for multiple search_tools at once."""
    resolved = [
        {"tool_type": "tavily", "api_key": "tvly-123"},
        {"tool_type": "perplexity", "api_key": "pplx-456"},
        {"tool_type": "wikipedia", "api_key": ""},
    ]
    params = {
        "search_tools": [
            {"tool_type": "wikipedia"},
            {"tool_type": "tavily"},
        ]
    }
    adapters = _build_search_adapters(params, resolved)
    assert adapters is not None
    assert len(adapters) == 2
    types = {a.tool_type for a in adapters}
    assert types == {"wikipedia", "tavily"}
    # Wikipedia has no key; Tavily got resolved.
    tavily = next(a for a in adapters if a.tool_type == "tavily")
    assert tavily.api_key == "tvly-123"


def test_build_search_adapters_resolved_none():
    """Returns None for unknown tool_type even with resolved_tools."""
    resolved = [{"tool_type": "tavily", "api_key": "tvly-123"}]
    params = {"search_tools": [{"tool_type": "unknown_tool"}]}
    adapters = _build_search_adapters(params, resolved)
    assert adapters is None


# ── End-to-end with real LLM (--real-llm flag) ───────────────────────────


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_web_agent_real_llm_pure(use_real_llm: bool, real_llm_config: dict):
    """E2E: pure LLM mode — planner → fetch → evaluate with a real provider.

    Requires ``--real-llm`` and env vars (see conftest.py).
    Uses a well-known Wikipedia topic so the LLM can generate real URLs.
    """
    if not use_real_llm:
        pytest.skip("--real-llm flag not set")

    # Wikipedia has a stable article on this topic.
    results = await run_web_agent(
        query="Python programming language history and features",
        llm_config=real_llm_config,
        max_iterations=2,
        search_adapters=None,
    )

    assert isinstance(results, list)
    # With a real LLM, 2 rounds of planner→fetch→evaluate should yield
    # at least one snippet on a well-known topic like Python.
    assert len(results) >= 1, (
        f"Expected at least 1 result, got {len(results)}. "
        "The LLM should generate fetchable URLs for a well-known topic."
    )
    for r in results:
        assert r.title, "Every result must have a title"
        assert r.url, "Every result must have a URL"
        assert r.snippet or r.content, (
            f"Result '{r.title}' must have snippet or content"
        )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_web_agent_real_llm_hybrid_wikipedia(
    use_real_llm: bool,
    real_llm_config: dict,
    wikipedia_adapter,
):
    """E2E: hybrid mode with a real Wikipedia adapter as seed.

    Requires ``--real-llm`` and ``PDF2TEX_TEST_PROVIDER`` / ``PDF2TEX_TEST_MODEL``.
    Wikipedia is free (no API key) so it always works as a search adapter.
    """
    if not use_real_llm:
        pytest.skip("--real-llm flag not set")

    results = await run_web_agent(
        query="Alan Turing biography and contributions",
        llm_config=real_llm_config,
        max_iterations=2,
        search_adapters=[wikipedia_adapter],
    )

    assert isinstance(results, list)
    # Wikipedia should contribute at least one result.
    assert len(results) >= 1, (
        "Expected at least 1 result from hybrid mode (Wikipedia adapter)"
    )
    for r in results:
        assert r.title, "Every result must have a title"
        assert r.url, "Every result must have a URL"
        assert r.snippet or r.content, (
            f"Result '{r.title}' must have snippet or content"
        )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_web_agent_real_llm_search_tools(
    use_real_llm: bool,
    real_llm_config: dict,
):
    """E2E: WebAgentAdapter with search_tools resolved via _resolved_web_tools.

    Exercises the full path: ``WebAgentAdapter.search()`` →
    ``_build_search_adapters(params, resolved)`` → API key resolution →
    ``run_web_agent(adapters=[...])``.

    Uses Wikipedia (free, no API key) and optionally Tavily if
    ``PDF2TEX_TEST_TAVILY_KEY`` is set in the environment.
    """
    if not use_real_llm:
        pytest.skip("--real-llm flag not set")

    import os

    # Build the full resolved_tools list — these simulate what the runner
    # builds from the DB with decrypted API keys.
    resolved_tools: list[dict[str, object]] = [
        {"tool_type": "wikipedia", "api_key": ""},
    ]
    search_tools: list[dict[str, str]] = [
        {"tool_type": "wikipedia"},
    ]

    # Optionally include Tavily if a key is available.
    tavily_key = os.environ.get("PDF2TEX_TEST_TAVILY_KEY", "")
    if tavily_key:
        resolved_tools.append({"tool_type": "tavily", "api_key": tavily_key})
        search_tools.append({"tool_type": "tavily"})

    # Create the WebAgentAdapter with _resolved_web_tools injected.
    agent_config: dict[str, object] = {
        "tool_type": "web_agent",
        "api_key": "",
        "base_url": "",
        "params": {
            "max_iterations": 2,
            "llm_config": real_llm_config,
            "search_tools": search_tools,
        },
        "_resolved_web_tools": resolved_tools,
    }

    from app.services.web_search import WebAgentAdapter

    agent = WebAgentAdapter(agent_config)
    results = await agent.search("artificial intelligence history")

    assert isinstance(results, list)
    assert len(results) >= 1, (
        f"Expected at least 1 result from WebAgentAdapter.search() "
        f"with search_tools={[s['tool_type'] for s in search_tools]}, "
        f"got {len(results)}"
    )
    for r in results:
        assert r.title, "Every result must have a title"
        assert r.url, "Every result must have a URL"
        assert r.snippet or r.content, (
            f"Result '{r.title}' must have snippet or content"
        )
