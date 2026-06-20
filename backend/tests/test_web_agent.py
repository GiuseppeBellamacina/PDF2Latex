"""Integration tests for the multi-node Web Agent LangGraph flow.

Covers:
- Routing (_after_evaluator, _fan_out_to_search)
- planner_node (mocked LLM → PlannedQueries)
- _make_search_node factory (fan-out search nodes)
- deduplicator_node (URL normalisation, dedup, visited filtering)
- merger_node (page fetching, content injection)
- evaluator_node (mocked LLM → EvalResult)
- custom_urls_node (URL fetching)
- Full graph run (run_web_agent with mocked LLM + mocked HTTP)
- Fan-out / dedup / merge integration
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.web_agent import (
    EvalResult,
    PlannedQueries,
    WebAgentState,
    _after_evaluator,
    _fan_out_to_search,
    _make_search_node,
    build_web_agent_graph,
    custom_urls_node,
    deduplicator_node,
    evaluator_node,
    merger_node,
    planner_node,
    run_web_agent,
)
from app.services.web_search import SearchResult

LLM = {"provider": "fake", "model": "test"}


# ============================================================================
# Helpers
# ============================================================================


def _make_result(
    title: str, url: str = "", content: str = "", snippet: str = ""
) -> SearchResult:
    return SearchResult(
        title=title,
        url=url,
        snippet=snippet or content[:500],
        content=content[:8000],
    )


def _planner_mock(
    queries: dict | None = None, urls: list[str] | None = None
) -> PlannedQueries:
    return PlannedQueries(
        queries=queries or {},
        custom_urls=urls or [],
        reasoning="Test reasoning.",
    )


def _eval_mock(
    satisfied: bool = True,
    snippets: list[dict] | None = None,
    refined_queries: dict | None = None,
    refined_urls: list[str] | None = None,
) -> EvalResult:
    return EvalResult(
        snippets=snippets or [],
        reasoning="Test evaluation.",
        is_satisfied=satisfied,
        refined_queries=refined_queries or {},
        refined_urls=refined_urls or [],
    )


# ============================================================================
# Routing tests
# ============================================================================


def test_after_evaluator_satisfied():
    assert (
        _after_evaluator({"is_complete": True, "iteration": 1, "max_iterations": 3})
        == "__end__"
    )


def test_after_evaluator_max_iterations():
    assert (
        _after_evaluator({"is_complete": False, "iteration": 3, "max_iterations": 3})
        == "__end__"
    )


def test_after_evaluator_continue():
    assert (
        _after_evaluator({"is_complete": False, "iteration": 1, "max_iterations": 3})
        == "planner"
    )


def test_after_evaluator_iteration_zero():
    assert (
        _after_evaluator({"is_complete": False, "iteration": 0, "max_iterations": 3})
        == "planner"
    )


# ============================================================================
# _fan_out_to_search tests
# ============================================================================


def test_fan_out_routes_to_tools_with_queries():
    """Routes only to nodes that exist AND have queries."""
    state: WebAgentState = {
        "per_tool_queries": {"wikipedia": ["q1"], "arxiv": ["q2"], "tavily": []},
        "custom_urls": [],
    }
    valid = {"wikipedia", "arxiv", "tavily", "custom_urls"}
    routes = _fan_out_to_search(state, valid)
    assert routes == ["wikipedia", "arxiv"]


def test_fan_out_includes_custom_urls():
    """Custom URLs node is included when URLs are planned."""
    state: WebAgentState = {
        "per_tool_queries": {},
        "custom_urls": ["https://example.com"],
    }
    valid = {"wikipedia", "arxiv", "custom_urls"}
    routes = _fan_out_to_search(state, valid)
    assert routes == ["custom_urls"]


def test_fan_out_fallback_to_deduplicator():
    """When nothing to search, fall back to deduplicator."""
    state: WebAgentState = {
        "per_tool_queries": {},
        "custom_urls": [],
    }
    routes = _fan_out_to_search(state, {"wikipedia", "arxiv", "custom_urls"})
    assert routes == ["deduplicator"]


def test_fan_out_respects_valid_nodes():
    """Only routes to nodes in valid_nodes, even if planner generated queries for others."""
    state: WebAgentState = {
        "per_tool_queries": {
            "wikipedia": ["q1"],
            "tavily": ["q2"],
            "perplexity": ["q3"],
        },
        "custom_urls": ["https://x.com"],
    }
    # Graph only has wikipedia + custom_urls nodes.
    valid = {"wikipedia", "custom_urls"}
    routes = _fan_out_to_search(state, valid)
    assert routes == ["wikipedia", "custom_urls"]


# ============================================================================
# planner_node tests
# ============================================================================


@pytest.mark.asyncio
async def test_planner_generates_queries_and_urls():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=PlannedQueries(
                queries={
                    "wikipedia": ["deep learning"],
                    "arxiv": ["neural networks survey"],
                },
                custom_urls=["https://example.com/article"],
                reasoning="Broad search needed.",
            )
        ),
    ):
        result = await planner_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "collected_results": [],
            }
        )

    assert result["per_tool_queries"]["wikipedia"] == ["deep learning"]
    assert result["per_tool_queries"]["arxiv"] == ["neural networks survey"]
    assert result["custom_urls"] == ["https://example.com/article"]
    assert "Broad search needed" in result["planner_reasoning"]
    assert result["new_results"] == []
    assert result["scraped_content"] == {}


@pytest.mark.asyncio
async def test_planner_fallback_on_error():
    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=RuntimeError("structured failed")),
        ),
        patch(
            "app.agents.web_agent.call_llm",
            AsyncMock(return_value="Fallback reasoning."),
        ),
    ):
        result = await planner_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "collected_results": [],
            }
        )

    assert result["per_tool_queries"]["tavily"] == ["machine learning"]
    assert result["per_tool_queries"]["wikipedia"] == ["machine learning"]
    assert result["custom_urls"] == []
    assert "Fallback reasoning" in result["planner_reasoning"]


@pytest.mark.asyncio
async def test_planner_sees_collected_context():
    """The planner's user prompt includes titles from collected results."""
    collected = [
        SearchResult(
            title="Intro to ML",
            url="https://x.com/ml",
            snippet="ML basics.",
            content="ML is...",
        ),
    ]
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(return_value=_planner_mock()),
    ) as mock_structured:
        await planner_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "collected_results": collected,
            }
        )

    call_args = mock_structured.call_args
    user_prompt = call_args[0][2]  # third positional arg = user message
    assert "Intro to ML" in user_prompt


# ============================================================================
# _make_search_node tests
# ============================================================================


@pytest.mark.asyncio
async def test_search_node_calls_search_fn():
    """The factory-created node calls search_fn for each query and returns results."""
    search_fn = AsyncMock(
        return_value=[
            _make_result("Result 1", "https://a.com", "Content A"),
            _make_result("Result 2", "https://b.com", "Content B"),
        ]
    )
    node = _make_search_node("wikipedia", search_fn)

    result = await node(
        {
            "per_tool_queries": {"wikipedia": ["q1", "q2"]},
        }
    )

    assert len(result["new_results"]) == 4  # 2 queries × 2 results each
    assert search_fn.call_count == 2
    titles = {r.title for r in result["new_results"]}
    assert titles == {"Result 1", "Result 2"}


@pytest.mark.asyncio
async def test_search_node_handles_exception():
    """When a query fails, the node logs and continues with remaining queries."""
    call_count = 0

    async def flaky_search(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("network error")
        return [_make_result("OK", "https://ok.com", "OK content")]

    node = _make_search_node("tavily", flaky_search)

    result = await node(
        {
            "per_tool_queries": {"tavily": ["q1", "q2"]},
        }
    )

    assert len(result["new_results"]) == 1
    assert result["new_results"][0].title == "OK"


@pytest.mark.asyncio
async def test_search_node_empty_queries():
    """When the tool has no planned queries, returns empty list."""
    search_fn = AsyncMock()
    node = _make_search_node("wikipedia", search_fn)

    result = await node(
        {
            "per_tool_queries": {},
        }
    )

    assert result["new_results"] == []
    search_fn.assert_not_called()


# ============================================================================
# custom_urls_node tests
# ============================================================================


@pytest.mark.asyncio
async def test_custom_urls_fetches_pages():
    with patch(
        "app.agents.web_agent._fetch_url",
        AsyncMock(side_effect=lambda u: (u, f"Content from {u}")),
    ):
        result = await custom_urls_node(
            {
                "custom_urls": ["https://a.com", "https://b.com"],
                "visited_urls": [],
            }
        )

    assert len(result["new_results"]) == 2
    assert result["new_results"][0].url == "https://a.com"
    assert result["new_results"][0].content == "Content from https://a.com"
    assert result["scraped_content"]["https://a.com"] == "Content from https://a.com"


@pytest.mark.asyncio
async def test_custom_urls_filters_visited():
    with patch(
        "app.agents.web_agent._fetch_url",
        AsyncMock(side_effect=lambda u: (u, f"Content from {u}")),
    ):
        result = await custom_urls_node(
            {
                "custom_urls": ["https://old.com", "https://new.com"],
                "visited_urls": ["https://old.com"],
            }
        )

    assert len(result["new_results"]) == 1
    assert result["new_results"][0].url == "https://new.com"


# ============================================================================
# deduplicator_node tests
# ============================================================================


@pytest.mark.asyncio
async def test_deduplicator_removes_duplicate_urls():
    """Same URL from two sources → kept once."""
    results = [
        _make_result("A from tool1", "https://same.com", "Content A1"),
        _make_result("A from tool2", "https://same.com", "Content A2 longer content"),
        _make_result("B unique", "https://unique.com", "Content B"),
    ]
    result = await deduplicator_node(
        {
            "new_results": results,
            "visited_urls": [],
        }
    )

    assert len(result["deduped_results"]) == 2  # A (best) + B
    urls = {r.url for r in result["deduped_results"]}
    assert urls == {"https://same.com", "https://unique.com"}
    # The one with longer content was kept.
    kept_a = next(r for r in result["deduped_results"] if r.url == "https://same.com")
    assert len(kept_a.content) > len("Content A1")


@pytest.mark.asyncio
async def test_deduplicator_filters_visited_urls():
    """URLs already in visited_urls are dropped entirely."""
    results = [
        _make_result("Already seen", "https://seen.com", "Old"),
        _make_result("New page", "https://new.com", "New content"),
    ]
    result = await deduplicator_node(
        {
            "new_results": results,
            "visited_urls": ["https://seen.com"],
        }
    )

    assert len(result["deduped_results"]) == 1
    assert result["deduped_results"][0].url == "https://new.com"


@pytest.mark.asyncio
async def test_deduplicator_preserves_no_url_results():
    """Results with no URL (e.g., Perplexity answers) are always kept."""
    results = [
        _make_result("Answer block", "", "Perplexity answer text"),
        _make_result("Answer block", "", "Duplicate answer"),  # same title, no URL
    ]
    result = await deduplicator_node(
        {
            "new_results": results,
            "visited_urls": [],
        }
    )

    # Both kept because they have no URL — can't dedup by URL.
    assert len(result["deduped_results"]) == 2


@pytest.mark.asyncio
async def test_deduplicator_adds_to_visited():
    """Visited URLs are appended to the visited list."""
    results = [
        _make_result("Page A", "https://a.com", "A"),
        _make_result("Page B", "https://b.com", "B"),
    ]
    result = await deduplicator_node(
        {
            "new_results": results,
            "visited_urls": ["https://prior.com"],
        }
    )

    assert result["visited_urls"] == [
        "https://prior.com",
        "https://a.com",
        "https://b.com",
    ]


# ============================================================================
# merger_node tests
# ============================================================================


@pytest.mark.asyncio
async def test_merger_fetches_url_only_results():
    """Results with URL but no content trigger a fetch."""
    deduped = [
        _make_result("Has content", "https://with.com", "Full content already"),
        _make_result("No content", "https://fetchme.com", ""),  # URL-only, needs fetch
    ]
    with patch(
        "app.agents.web_agent._fetch_url",
        AsyncMock(return_value=("https://fetchme.com", "Fetched page text.")),
    ):
        result = await merger_node(
            {
                "deduped_results": deduped,
                "scraped_content": {},
                "collected_results": [],
            }
        )

    # Both results merged into collected.
    assert len(result["collected_results"]) == 2
    # The URL-only result now has content.
    fetched = next(
        r for r in result["collected_results"] if r.url == "https://fetchme.com"
    )
    assert fetched.content == "Fetched page text."
    assert fetched.snippet == "Fetched page text."[:500]


@pytest.mark.asyncio
async def test_merger_injects_scraped_content():
    """Pre-existing scraped content is injected without re-fetching."""
    deduped = [
        _make_result("No content", "https://x.com", ""),
    ]
    result = await merger_node(
        {
            "deduped_results": deduped,
            "scraped_content": {"https://x.com": "Already scraped text."},
            "collected_results": [],
        }
    )

    assert result["collected_results"][0].content == "Already scraped text."


@pytest.mark.asyncio
async def test_merger_combines_with_collected():
    """New deduped results are appended to the existing collected list."""
    existing = [_make_result("Old", "https://old.com", "Old content")]
    new_deduped = [_make_result("New", "https://new.com", "New content")]

    result = await merger_node(
        {
            "deduped_results": new_deduped,
            "scraped_content": {},
            "collected_results": existing,
        }
    )

    assert len(result["collected_results"]) == 2
    assert result["collected_results"][0].title == "Old"
    assert result["collected_results"][1].title == "New"
    assert result["deduped_results"] == []  # consumed


@pytest.mark.asyncio
async def test_merger_does_not_re_fetch_already_have_content():
    """Results that already have content are not re-fetched."""
    deduped = [_make_result("Rich", "https://rich.com", "I already have content")]

    with patch("app.agents.web_agent._fetch_url") as mock_fetch:
        result = await merger_node(
            {
                "deduped_results": deduped,
                "scraped_content": {},
                "collected_results": [],
            }
        )

    mock_fetch.assert_not_called()
    assert result["collected_results"][0].content == "I already have content"


# ============================================================================
# evaluator_node tests
# ============================================================================


@pytest.mark.asyncio
async def test_evaluator_extracts_snippets():
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=_eval_mock(
                satisfied=True,
                snippets=[
                    {
                        "title": "ML Overview",
                        "url": "https://x.com",
                        "content": "ML is a field.",
                    }
                ],
            )
        ),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {"https://x.com": "ML is a field."},
                "collected_results": [],
                "iteration": 0,
            }
        )

    assert result["is_complete"] is True
    assert result["iteration"] == 1
    assert len(result["collected_results"]) == 1
    assert result["collected_results"][0].title == "ML Overview"


@pytest.mark.asyncio
async def test_evaluator_not_satisfied_with_refined_queries():
    """When not satisfied, refined_queries and URLs are passed back for the next pass."""
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=_eval_mock(
                satisfied=False,
                snippets=[
                    {
                        "title": "Partial",
                        "url": "https://p.com",
                        "content": "Partial info.",
                    }
                ],
                refined_queries={"wikipedia": ["deep dive"], "arxiv": ["survey"]},
                refined_urls=["https://deeper.com"],
            )
        ),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {},
                "collected_results": [],
                "iteration": 0,
            }
        )

    assert result["is_complete"] is False
    assert result["per_tool_queries"]["wikipedia"] == ["deep dive"]
    assert result["per_tool_queries"]["arxiv"] == ["survey"]
    assert result["custom_urls"] == ["https://deeper.com"]


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
                "iteration": 0,
            }
        )

    assert result["is_complete"] is True  # fails safe
    assert result["collected_results"] == []
    assert result["per_tool_queries"] == {}


@pytest.mark.asyncio
async def test_evaluator_merges_previous_results():
    existing = [_make_result("Previous", "https://old.com", "Old content")]
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=_eval_mock(
                satisfied=True,
                snippets=[
                    {"title": "New", "url": "https://new.com", "content": "New content"}
                ],
            )
        ),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {"https://new.com": "New content"},
                "collected_results": existing,
                "iteration": 0,
            }
        )

    assert len(result["collected_results"]) == 2
    assert result["collected_results"][0].title == "Previous"
    assert result["collected_results"][1].title == "New"


@pytest.mark.asyncio
async def test_evaluator_skips_invalid_snippets():
    """Snippets with empty title or content are dropped."""
    with patch(
        "app.agents.web_agent.call_llm_structured",
        AsyncMock(
            return_value=_eval_mock(
                satisfied=True,
                snippets=[
                    {"title": "", "url": "x", "content": "no title"},  # dropped
                    {"title": "Good", "url": "x", "content": ""},  # dropped
                    {
                        "title": "Valid",
                        "url": "https://valid.com",
                        "content": "Valid content.",
                    },  # kept
                ],
            )
        ),
    ):
        result = await evaluator_node(
            {
                "llm_config": LLM,
                "query": "machine learning",
                "scraped_content": {},
                "collected_results": [],
                "iteration": 0,
            }
        )

    assert len(result["collected_results"]) == 1
    assert result["collected_results"][0].title == "Valid"


# ============================================================================
# Full graph integration — mocked LLM + mocked HTTP
# ============================================================================


def _make_httpx_mock_for_wikipedia(page_titles: list[str]):
    """Build a side_effect list of mocks for httpx.AsyncClient.get() that
    simulates a WikipediaAdapter.search() call sequence:
    1 search response + N extract responses (one per page)."""

    from unittest.mock import MagicMock

    mocks = []

    # 1. Search response.
    search_json = {
        "batchcomplete": "",
        "query": {
            "search": [
                {"title": t, "pageid": 1000 + i, "snippet": f"Snippet for {t}."}
                for i, t in enumerate(page_titles)
            ]
        },
    }
    search_mock = MagicMock()
    search_mock.json.return_value = search_json
    search_mock.raise_for_status = MagicMock()
    mocks.append(search_mock)

    # 2. Extract responses (one per page).
    for i, title in enumerate(page_titles):
        pid = 1000 + i
        extract_json = {
            "query": {
                "pages": {
                    str(pid): {
                        "pageid": pid,
                        "title": title,
                        "extract": f"Full extract text for {title}.",
                    }
                }
            }
        }
        extract_mock = MagicMock()
        extract_mock.json.return_value = extract_json
        extract_mock.raise_for_status = MagicMock()
        mocks.append(extract_mock)

    return mocks


@pytest.mark.asyncio
async def test_run_web_agent_single_pass():
    """Full graph: planner → fan_out(wikipedia) → dedup → merge → evaluate(satisfied) → END."""
    wikipedia_mocks = _make_httpx_mock_for_wikipedia(
        ["Deep learning", "Neural networks"]
    )

    async def llm_side_effect(*args, **kwargs):
        label = kwargs.get("label", "")
        if "planner" in label:
            return PlannedQueries(
                queries={"wikipedia": ["deep learning"]},
                custom_urls=[],
                reasoning="Search Wikipedia.",
            )
        # evaluator
        return EvalResult(
            snippets=[
                {
                    "title": "Deep learning",
                    "url": "https://en.wikipedia.org/wiki/Deep_learning",
                    "content": "Deep learning is...",
                },
            ],
            reasoning="Good enough.",
            is_satisfied=True,
            refined_queries={},
            refined_urls=[],
        )

    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=llm_side_effect),
        ),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        # httpx.AsyncClient().__aenter__().get() returns the mocks in sequence.
        mock_get = AsyncMock(side_effect=wikipedia_mocks)
        mock_ctx = MagicMock()
        mock_ctx.get = mock_get
        mock_client_cls.return_value.__aenter__.return_value = mock_ctx

        results = await run_web_agent(
            query="deep learning",
            llm_config=LLM,
            max_iterations=1,
            search_adapters=None,  # uses built-in Wikipedia
        )

    assert len(results) >= 1
    titles = {r.title for r in results}
    assert "Deep learning" in titles


@pytest.mark.asyncio
async def test_run_web_agent_multi_pass():
    """Two passes: planner → fan_out → ... → evaluator(not satisfied) → planner → ... → END."""
    wikipedia_mocks = _make_httpx_mock_for_wikipedia(
        ["Topic A"]
    ) + _make_httpx_mock_for_wikipedia(["Topic B"])

    pass_count = [0]

    async def llm_side_effect(*args, **kwargs):
        label = kwargs.get("label", "")
        if "planner" in label:
            pass_count[0] += 1
            return PlannedQueries(
                queries={"wikipedia": [f"query pass {pass_count[0]}"]},
                custom_urls=[],
                reasoning=f"Pass {pass_count[0]}.",
            )
        # evaluator
        if pass_count[0] < 2:
            return EvalResult(
                snippets=[
                    {
                        "title": f"Result pass {pass_count[0]}",
                        "url": f"https://x.com/p{pass_count[0]}",
                        "content": "Partial.",
                    }
                ],
                reasoning="Need more.",
                is_satisfied=False,
                refined_queries={"wikipedia": ["more"]},
                refined_urls=[],
            )
        return EvalResult(
            snippets=[
                {
                    "title": f"Result pass {pass_count[0]}",
                    "url": f"https://x.com/p{pass_count[0]}",
                    "content": "Complete.",
                }
            ],
            reasoning="Done.",
            is_satisfied=True,
            refined_queries={},
            refined_urls=[],
        )

    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=llm_side_effect),
        ),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_get = AsyncMock(side_effect=wikipedia_mocks)
        mock_ctx = MagicMock()
        mock_ctx.get = mock_get
        mock_client_cls.return_value.__aenter__.return_value = mock_ctx

        results = await run_web_agent(
            query="deep learning",
            llm_config=LLM,
            max_iterations=3,
            search_adapters=None,
        )

    assert pass_count[0] >= 2  # at least 2 planner invocations
    assert len(results) >= 2  # results from both passes accumulated


@pytest.mark.asyncio
async def test_run_web_agent_no_adapters_works():
    """run_web_agent works with search_adapters=None (pure LLM + built-in Wikipedia)."""
    wikipedia_mocks = _make_httpx_mock_for_wikipedia(["Test"])

    async def llm_side_effect(*args, **kwargs):
        label = kwargs.get("label", "")
        if "planner" in label:
            return PlannedQueries(
                queries={"wikipedia": ["test"]},
                custom_urls=[],
                reasoning="Test.",
            )
        return EvalResult(
            snippets=[],
            reasoning="OK.",
            is_satisfied=True,
            refined_queries={},
            refined_urls=[],
        )

    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(side_effect=llm_side_effect),
        ),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_get = AsyncMock(side_effect=wikipedia_mocks)
        mock_ctx = MagicMock()
        mock_ctx.get = mock_get
        mock_client_cls.return_value.__aenter__.return_value = mock_ctx

        results = await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=1,
            search_adapters=None,
        )

    assert isinstance(results, list)
    assert len(results) >= 1


# ============================================================================
# Integration: fan-out + dedup + merge pipeline
# ============================================================================


@pytest.mark.asyncio
async def test_fan_out_multiple_search_nodes_in_parallel():
    """Two search adapters (mock) run as parallel nodes, results fan-in."""
    adapter1 = AsyncMock()
    adapter1.tool_type = "wikipedia"
    adapter1.search = AsyncMock(
        return_value=[
            _make_result("Wiki Page", "https://wiki.com/page", "Wiki content"),
        ]
    )

    adapter2 = AsyncMock()
    adapter2.tool_type = "arxiv"
    adapter2.search = AsyncMock(
        return_value=[
            _make_result(
                "arXiv Paper",
                "https://arxiv.org/abs/2301.12345",
                "arXiv abstract",
                "arXiv abstract...",
            ),
        ]
    )

    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(
                side_effect=[
                    # planner
                    PlannedQueries(
                        queries={"wikipedia": ["q1"], "arxiv": ["q2"]},
                        custom_urls=[],
                        reasoning="Two tools.",
                    ),
                    # evaluator
                    _eval_mock(
                        satisfied=True,
                        snippets=[
                            {
                                "title": "Wiki Page",
                                "url": "https://wiki.com/page",
                                "content": "Wiki content",
                            },
                            {
                                "title": "arXiv Paper",
                                "url": "https://arxiv.org/abs/2301.12345",
                                "content": "arXiv abstract...",
                            },
                        ],
                    ),
                ]
            ),
        ),
    ):
        results = await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=1,
            search_adapters=[adapter1, adapter2],
        )

    # Both adapters were called.
    adapter1.search.assert_called_once()
    adapter2.search.assert_called_once()

    # Results from both adapters appear.
    titles = {r.title for r in results}
    assert "Wiki Page" in titles
    assert "arXiv Paper" in titles


@pytest.mark.asyncio
async def test_adapter_failure_does_not_block_graph():
    """When one adapter raises RuntimeError, the other adapter still contributes
    and the full graph completes without crashing."""
    adapter_good = AsyncMock()
    adapter_good.tool_type = "arxiv"
    adapter_good.search = AsyncMock(
        return_value=[
            _make_result(
                "arXiv Paper",
                "https://arxiv.org/abs/2501.00001",
                "arXiv content",
                "arXiv content",
            ),
        ]
    )

    adapter_bad = AsyncMock()
    adapter_bad.tool_type = "tavily"
    adapter_bad.search = AsyncMock(side_effect=RuntimeError("Tavily API timeout"))

    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(
                side_effect=[
                    PlannedQueries(
                        queries={"arxiv": ["q1"], "tavily": ["q2"]},
                        custom_urls=[],
                        reasoning="Two tools, one may fail.",
                    ),
                    _eval_mock(
                        satisfied=True,
                        snippets=[
                            {
                                "title": "arXiv Paper",
                                "url": "https://arxiv.org/abs/2501.00001",
                                "content": "arXiv content",
                            },
                        ],
                    ),
                ]
            ),
        ),
    ):
        results = await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=1,
            search_adapters=[adapter_good, adapter_bad],
        )

    # The good adapter was called and contributed.
    adapter_good.search.assert_called_once()
    adapter_bad.search.assert_called_once()

    # The flow did not crash — we have results from the good adapter.
    assert len(results) >= 1
    titles = {r.title for r in results}
    assert "arXiv Paper" in titles


@pytest.mark.asyncio
async def test_dedup_across_tools():
    """When two tools return the same URL, the deduplicator keeps only one (best content)."""
    adapter1 = AsyncMock()
    adapter1.tool_type = "wikipedia"
    adapter1.search = AsyncMock(
        return_value=[
            _make_result("Same Page", "https://same.com/article", "Short snippet"),
        ]
    )

    adapter2 = AsyncMock()
    adapter2.tool_type = "arxiv"
    adapter2.search = AsyncMock(
        return_value=[
            _make_result(
                "Same Page (richer)",
                "https://same.com/article",
                "Much longer content with full text from the page including many details and examples.",
            ),
        ]
    )

    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(
                side_effect=[
                    PlannedQueries(
                        queries={"wikipedia": ["q1"], "arxiv": ["q2"]},
                        custom_urls=[],
                        reasoning="Both.",
                    ),
                    _eval_mock(
                        satisfied=True,
                        snippets=[
                            {
                                "title": "Other Source",
                                "url": "https://other.com/page",
                                "content": "Different URL",
                            },
                        ],
                    ),
                ]
            ),
        ),
    ):
        results = await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=1,
            search_adapters=[adapter1, adapter2],
        )

    # The deduplicator should have removed the duplicate URL.
    # Only 1 result with same.com URL (the richer one, deduped).
    same_url_results = [r for r in results if "same.com" in r.url]
    assert len(same_url_results) == 1
    # The kept result has the richer content.
    assert "longer content" in same_url_results[0].content


@pytest.mark.asyncio
async def test_merger_fetches_content_for_url_only_results():
    """URL-only results from search adapters get full content in the merger."""
    adapter = AsyncMock()
    adapter.tool_type = "wikipedia"
    adapter.search = AsyncMock(
        return_value=[
            _make_result("URL only", "https://fetch.com/deep", ""),  # no content
        ]
    )

    with (
        patch(
            "app.agents.web_agent.call_llm_structured",
            AsyncMock(
                side_effect=[
                    PlannedQueries(
                        queries={"wikipedia": ["q1"]},
                        custom_urls=[],
                        reasoning="Search.",
                    ),
                    _eval_mock(
                        satisfied=True,
                        snippets=[
                            {
                                "title": "Other",
                                "url": "https://other.com",
                                "content": "Other content",
                            },
                        ],
                    ),
                ]
            ),
        ),
        patch(
            "app.agents.web_agent._fetch_url",
            AsyncMock(return_value=("https://fetch.com/deep", "Fetched content!")),
        ),
    ):
        results = await run_web_agent(
            query="test",
            llm_config=LLM,
            max_iterations=1,
            search_adapters=[adapter],
        )

    # The URL-only result should have gotten content via the merger fetch.
    url_only = [r for r in results if "fetch.com" in r.url]
    assert len(url_only) == 1
    assert url_only[0].content == "Fetched content!"


# ============================================================================
# build_web_agent_graph
# ============================================================================


def test_build_graph_returns_compiled_graph():
    graph = build_web_agent_graph()
    assert graph is not None
    assert hasattr(graph, "ainvoke")


def test_build_graph_with_custom_adapters():
    """Custom adapters become nodes; web_agent adapter is skipped (no recursion)."""
    adapter = AsyncMock()
    adapter.tool_type = "tavily"
    adapter.search = AsyncMock(return_value=[])

    graph = build_web_agent_graph(search_adapters=[adapter])
    assert graph is not None
    assert hasattr(graph, "ainvoke")


# ============================================================================
# Real-LLM E2E tests (require --real-llm flag)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_web_agent_real_llm_pure(use_real_llm: bool, real_llm_config: dict):
    """E2E: pure LLM + built-in Wikipedia → planner → fan_out → ... → END."""
    if not use_real_llm:
        pytest.skip("--real-llm flag not set")

    results = await run_web_agent(
        query="Python programming language history and features",
        llm_config=real_llm_config,
        max_iterations=2,
        search_adapters=None,
    )

    assert isinstance(results, list)
    assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}."
    for r in results:
        assert r.title, "Every result must have a title"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_web_agent_real_llm_with_wikipedia(
    use_real_llm: bool,
    real_llm_config: dict,
    wikipedia_adapter,
):
    """E2E: hybrid mode with real Wikipedia adapter."""
    if not use_real_llm:
        pytest.skip("--real-llm flag not set")

    results = await run_web_agent(
        query="Alan Turing biography and contributions",
        llm_config=real_llm_config,
        max_iterations=2,
        search_adapters=[wikipedia_adapter],
    )

    assert isinstance(results, list)
    assert len(results) >= 1, "Expected at least 1 result from hybrid mode."
    for r in results:
        assert r.title, "Every result must have a title"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_web_agent_real_llm_search_tools(
    use_real_llm: bool,
    real_llm_config: dict,
    resolved_web_tools: list[dict[str, object]],
):
    """E2E: WebAgentAdapter with search_tools resolved via _resolved_web_tools."""
    if not use_real_llm:
        pytest.skip("--real-llm flag not set")

    search_tools: list[dict[str, str]] = [
        {"tool_type": str(t["tool_type"])} for t in resolved_web_tools
    ]

    agent_config: dict[str, object] = {
        "tool_type": "web_agent",
        "api_key": "",
        "base_url": "",
        "params": {
            "max_iterations": 2,
            "llm_config": real_llm_config,
            "search_tools": search_tools,
        },
        "_resolved_web_tools": resolved_web_tools,
    }

    from app.services.web_search import WebAgentAdapter

    agent = WebAgentAdapter(agent_config)
    results = await agent.search("artificial intelligence history")

    assert isinstance(results, list)
    assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}"
    for r in results:
        assert r.title, "Every result must have a title"
