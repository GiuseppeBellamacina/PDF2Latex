"""Tests for ``app.services.web_search`` adapters (ArxivAdapter, WikipediaAdapter).

Every test mocks ``httpx.AsyncClient`` so no real network call is made.
A valid arXiv Atom XML fixture or Wikipedia JSON fixture is returned by the
mock; the adapter's parsing logic is verified.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.web_search import ArxivAdapter, SearchResult, WikipediaAdapter

# ── Fixtures ────────────────────────────────────────────────────────────────

# A minimal arXiv Atom XML response with 2 entries.
_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>ArXiv Query: all:deep+learning+survey</title>
  <entry>
    <id>http://arxiv.org/abs/2301.12345v2</id>
    <title>Deep Learning: A Comprehensive Survey</title>
    <summary>  This paper provides a comprehensive survey of deep learning
techniques including CNNs, RNNs, and Transformers.  </summary>
    <published>2023-01-15T18:00:00Z</published>
    <author>
      <name>John Doe</name>
    </author>
    <author>
      <name>Jane Smith</name>
    </author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2305.67890v1</id>
    <title>Attention Mechanisms in Neural Networks</title>
    <summary>We review attention mechanisms and their applications.</summary>
    <published>2023-05-20T12:00:00Z</published>
    <author>
      <name>Alice Johnson</name>
    </author>
  </entry>
</feed>"""

# Single entry for edge-case tests.
_ARXIV_SINGLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2403.00001v1</id>
    <title>Minimal Paper</title>
    <summary>Short summary.</summary>
    <published>2024-03-01T00:00:00Z</published>
    <author><name>Single Author</name></author>
  </entry>
</feed>"""

# Entry with no authors (edge case).
_ARXIV_NO_AUTHORS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v3</id>
    <title>Untitled Work</title>
    <summary>No authors listed.</summary>
    <published>2023-01-01T00:00:00Z</published>
  </entry>
</feed>"""

# Entry with a non-standard arxiv ID (no version suffix).
_ARXIV_NO_VERSION = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/cs/0101001</id>
    <title>Old Format Paper</title>
    <summary>Legacy arXiv ID format.</summary>
    <published>2001-01-01T00:00:00Z</published>
    <author><name>Historic Author</name></author>
  </entry>
</feed>"""

# Entry with XML entities and newlines in title (escaping test).
_ARXIV_ESCAPED_TITLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <title>A &amp; B: compare &lt;X&gt; &amp; &quot;Y&quot; —
a multi-line title with
special chars</title>
    <summary>Escaping test.</summary>
    <published>2025-01-01T00:00:00Z</published>
    <author><name>Tester</name></author>
  </entry>
</feed>"""
_ARXIV_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
</feed>"""


def _mock_httpx(text: str):
    """Return an ``AsyncMock`` for ``httpx.AsyncClient`` that returns *text*."""
    mock_resp = MagicMock()
    mock_resp.text = text
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get.return_value = mock_resp
    return mock_client


def _adapter(max_results: int = 5) -> ArxivAdapter:
    """Create an ArxivAdapter with defaults suitable for testing."""
    return ArxivAdapter(
        {
            "tool_type": "arxiv",
            "api_key": "",
            "base_url": "",
            "params": {"max_results": max_results},
        }
    )


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parses_multiple_entries() -> None:
    """Two entries: both should be returned with correct metadata."""
    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_XML)):
        results = await adapter.search("deep learning survey")

    assert len(results) == 2

    # First entry.
    r1 = results[0]
    assert r1.title == "Deep Learning: A Comprehensive Survey"
    assert r1.url == "http://arxiv.org/abs/2301.12345v2"
    assert "CNNs" in r1.snippet
    assert "CNNs" in r1.content
    assert r1.authors == "John Doe, Jane Smith"
    assert r1.year == "2023"
    assert r1.venue == "arXiv:2301.12345"

    # Second entry.
    r2 = results[1]
    assert r2.title == "Attention Mechanisms in Neural Networks"
    assert r2.authors == "Alice Johnson"
    assert r2.year == "2023"
    assert r2.venue == "arXiv:2305.67890"


@pytest.mark.asyncio
async def test_strips_version_suffix() -> None:
    """arXiv ID '2301.12345v2' → venue 'arXiv:2301.12345'."""
    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_SINGLE)):
        results = await adapter.search("minimal")

    assert len(results) == 1
    assert results[0].venue == "arXiv:2403.00001"


@pytest.mark.asyncio
async def test_single_author() -> None:
    """Single author should not have trailing comma."""
    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_SINGLE)):
        results = await adapter.search("minimal")

    assert results[0].authors == "Single Author"


@pytest.mark.asyncio
async def test_no_authors() -> None:
    """Entry with no <author> elements → authors is empty string."""
    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_NO_AUTHORS)):
        results = await adapter.search("no authors")

    assert len(results) == 1
    assert results[0].authors == ""
    assert results[0].year == "2023"


@pytest.mark.asyncio
async def test_legacy_arxiv_id_format() -> None:
    """Old arXiv ID like 'cs/0101001' → venue uses full ID (no version strip)."""
    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_NO_VERSION)):
        results = await adapter.search("legacy")

    assert len(results) == 1
    # Legacy ID 'cs/0101001' now survives because we use split("/abs/")[-1].
    assert results[0].venue == "arXiv:cs/0101001"
    assert results[0].year == "2001"


@pytest.mark.asyncio
async def test_title_escapes_xml_entities_and_newlines() -> None:
    """XML entities (&amp;, &lt;, &quot;) are decoded and newlines collapsed."""
    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_ESCAPED_TITLE)):
        results = await adapter.search("escaping")

    assert len(results) == 1
    # XML entities decoded by ElementTree.
    assert "&amp;" not in results[0].title
    assert "&lt;" not in results[0].title
    # Actual decoded characters are present.
    assert "&" in results[0].title
    assert "<X>" in results[0].title
    assert '"Y"' in results[0].title
    # Newlines collapsed to single spaces.
    assert "\n" not in results[0].title
    assert "\r" not in results[0].title
    # The title reads as one clean line.
    assert "A & B: compare" in results[0].title
    assert "special chars" in results[0].title
    assert results[0].year == "2025"


@pytest.mark.asyncio
async def test_empty_feed_returns_empty_list() -> None:
    """A feed with no entries → empty list."""
    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_EMPTY)):
        results = await adapter.search("no results")

    assert results == []


@pytest.mark.asyncio
async def test_max_results_capped() -> None:
    """Adapter.max_results limits the number of returned entries."""
    adapter = _adapter(max_results=1)

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_XML)):
        results = await adapter.search("deep learning survey")

    # Feed has 2 entries, max_results=1 → only 1 returned.
    assert len(results) == 1
    assert results[0].title == "Deep Learning: A Comprehensive Survey"


@pytest.mark.asyncio
async def test_http_error_propagates() -> None:
    """HTTP errors from the arXiv API propagate to the caller."""
    adapter = _adapter()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(
        side_effect=RuntimeError("HTTP 503 Service Unavailable")
    )

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get.return_value = mock_resp

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="503"):
            await adapter.search("any query")


@pytest.mark.asyncio
async def test_snippet_truncated_to_500() -> None:
    """Snippet is capped at 500 chars, content at 8000."""
    long_summary = "X " * 600  # ~1200 chars
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001</id>
    <title>Long Paper</title>
    <summary>{long_summary}</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Author</name></author>
  </entry>
</feed>"""

    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(xml)):
        results = await adapter.search("long")

    assert len(results) == 1
    assert len(results[0].snippet) <= 500
    assert len(results[0].content) <= 8000


@pytest.mark.asyncio
async def test_result_is_searchresult_type() -> None:
    """Verify returned objects are SearchResult instances."""
    adapter = _adapter()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(_ARXIV_SINGLE)):
        results = await adapter.search("minimal")

    assert len(results) == 1
    assert isinstance(results[0], SearchResult)


# ============================================================================
# WikipediaAdapter tests
# ============================================================================

# Wikipedia search API response (action=query&list=search).
_WP_SEARCH_JSON = {
    "batchcomplete": "",
    "query": {
        "search": [
            {
                "title": "Deep learning",
                "pageid": 11001,
                "snippet": '<span class="searchmatch">Deep</span> <span class="searchmatch">learning</span> is a class of machine <span class="searchmatch">learning</span> algorithms that uses multiple layers to progressively extract higher-level features.',
            },
            {
                "title": "Artificial neural network",
                "pageid": 11002,
                "snippet": '<span class="searchmatch">Artificial</span> <span class="searchmatch">neural</span> <span class="searchmatch">networks</span> are computing systems inspired by biological neural networks.',
            },
            {
                "title": "Attention (machine learning)",
                "pageid": 11003,
                "snippet": '<span class="searchmatch">Attention</span> is a machine <span class="searchmatch">learning</span> technique that mimics cognitive attention.',
            },
        ]
    },
}

# Wikipedia extract API response — page 11001.
_WP_EXTRACT_11001 = {
    "query": {
        "pages": {
            "11001": {
                "pageid": 11001,
                "title": "Deep learning",
                "extract": "Deep learning is a class of machine learning algorithms that uses multiple layers to progressively extract higher-level features from the raw input. For example, in image processing, lower layers may identify edges, while higher layers may identify the concepts relevant to a human such as digits, letters, or faces.",
            }
        }
    },
}

# Wikipedia extract API response — page 11002.
_WP_EXTRACT_11002 = {
    "query": {
        "pages": {
            "11002": {
                "pageid": 11002,
                "title": "Artificial neural network",
                "extract": "Artificial neural networks (ANNs) are computing systems inspired by the biological neural networks that constitute animal brains. Such systems learn to perform tasks by considering examples.",
            }
        }
    },
}

# Wikipedia extract API response — page 11003.
_WP_EXTRACT_11003 = {
    "query": {
        "pages": {
            "11003": {
                "pageid": 11003,
                "title": "Attention (machine learning)",
                "extract": "In machine learning, attention is a technique that is meant to mimic cognitive attention.",
            }
        }
    },
}

# Empty Wikipedia search response.
_WP_SEARCH_EMPTY = {
    "batchcomplete": "",
    "query": {"search": []},
}

# Search response with a page that has no extract (e.g., missing page).
_WP_SEARCH_MISSING_PAGE = {
    "batchcomplete": "",
    "query": {
        "search": [
            {
                "title": "Ghost page",
                "pageid": 99999,
                "snippet": "This page does not exist.",
            },
        ]
    },
}

_WP_EXTRACT_MISSING = {
    "query": {
        "pages": {
            "99999": {
                "pageid": 99999,
                "title": "Ghost page",
                "missing": "",
            }
        }
    },
}

# Search response with no pageid (edge case).
_WP_SEARCH_NO_PAGEID = {
    "batchcomplete": "",
    "query": {
        "search": [
            {
                "title": "Page without ID",
                "snippet": "This result has no pageid.",
            },
        ]
    },
}


def _make_json_mock(data):
    """Create a mock HTTP response whose ``.json()`` returns *data*."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _wp_adapter(max_results: int = 5, language: str = "en") -> WikipediaAdapter:
    """Create a WikipediaAdapter with defaults suitable for testing."""
    return WikipediaAdapter(
        {
            "tool_type": "wikipedia",
            "api_key": "",
            "base_url": "",
            "params": {"max_results": max_results, "language": language},
        }
    )


def _mock_httpx_with_side_effect(responses: list):
    """Return an ``AsyncMock`` for ``httpx.AsyncClient`` that returns
    *responses* in sequence for successive ``.get()`` calls."""
    mock_client = AsyncMock()
    # Each get() call returns the next mock response.
    mock_client.__aenter__.return_value.get = AsyncMock(side_effect=responses)
    return mock_client


@pytest.mark.asyncio
async def test_wp_parses_multiple_results() -> None:
    """Three search results with extracts: titles, URLs, snippets, and content are correct."""
    adapter = _wp_adapter(max_results=3)

    # Prepare: one search response + three extract responses.
    mocks = [
        _make_json_mock(_WP_SEARCH_JSON),
        _make_json_mock(_WP_EXTRACT_11001),
        _make_json_mock(_WP_EXTRACT_11002),
        _make_json_mock(_WP_EXTRACT_11003),
    ]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("deep learning")

    assert len(results) == 3

    r0 = results[0]
    assert r0.title == "Deep learning"
    assert r0.url == "https://en.wikipedia.org/wiki/Deep_learning"
    assert "class of machine learning" in r0.snippet
    # HTML tags in snippet should be stripped.
    assert "<span" not in r0.snippet
    assert "searchmatch" not in r0.snippet
    assert "multiple layers" in r0.content
    assert r0.authors == ""
    assert r0.year == ""
    assert r0.venue == ""

    r1 = results[1]
    assert r1.title == "Artificial neural network"
    assert r1.url == "https://en.wikipedia.org/wiki/Artificial_neural_network"
    assert "computing systems" in r1.content

    r2 = results[2]
    assert r2.title == "Attention (machine learning)"
    assert "cognitive attention" in r2.content


@pytest.mark.asyncio
async def test_wp_empty_search_returns_empty_list() -> None:
    """Empty search response → []."""
    adapter = _wp_adapter()

    mocks = [_make_json_mock(_WP_SEARCH_EMPTY)]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("xyznonexistent123")

    assert results == []


@pytest.mark.asyncio
async def test_wp_max_results_capped() -> None:
    """max_results=2 on a feed with 3 hits → only 2 returned."""
    adapter = _wp_adapter(max_results=2)

    mocks = [
        _make_json_mock(_WP_SEARCH_JSON),
        _make_json_mock(_WP_EXTRACT_11001),
        _make_json_mock(_WP_EXTRACT_11002),
    ]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("deep learning")

    assert len(results) == 2
    assert results[0].title == "Deep learning"
    assert results[1].title == "Artificial neural network"


@pytest.mark.asyncio
async def test_wp_http_error_propagates() -> None:
    """HTTP error on the search request propagates to the caller."""
    adapter = _wp_adapter()

    bad_resp = MagicMock()
    bad_resp.raise_for_status = MagicMock(
        side_effect=RuntimeError("HTTP 503 Service Unavailable")
    )

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get = AsyncMock(return_value=bad_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="503"):
            await adapter.search("any query")


@pytest.mark.asyncio
async def test_wp_extract_failure_is_graceful() -> None:
    """When the extract API fails for a page, the result still appears
    but with empty content (no crash)."""
    adapter = _wp_adapter(max_results=1)

    bad_extract = MagicMock()
    bad_extract.raise_for_status = MagicMock(side_effect=RuntimeError("HTTP 500"))

    # Single-page search so only one extract call is made.
    search_single = {
        "batchcomplete": "",
        "query": {
            "search": [
                {
                    "title": "Deep learning",
                    "pageid": 11001,
                    "snippet": "Deep learning is a class of machine learning.",
                },
            ]
        },
    }

    mocks = [
        _make_json_mock(search_single),  # search OK
        bad_extract,  # extract fails
    ]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("deep learning")

    assert len(results) == 1
    assert results[0].title == "Deep learning"
    assert results[0].snippet != ""
    assert results[0].content == ""


@pytest.mark.asyncio
async def test_wp_missing_page_extract_is_empty() -> None:
    """Page with 'missing' key in extract → content is empty string."""
    adapter = _wp_adapter()

    mocks = [
        _make_json_mock(_WP_SEARCH_MISSING_PAGE),
        _make_json_mock(_WP_EXTRACT_MISSING),
    ]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("ghost")

    assert len(results) == 1
    assert results[0].title == "Ghost page"
    assert results[0].content == ""


@pytest.mark.asyncio
async def test_wp_page_without_pageid() -> None:
    """A search result without a pageid → no extract fetch, content is empty."""
    adapter = _wp_adapter()

    mocks = [_make_json_mock(_WP_SEARCH_NO_PAGEID)]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("no pageid")

    assert len(results) == 1
    assert results[0].title == "Page without ID"
    assert results[0].content == ""
    assert results[0].snippet == "This result has no pageid."


@pytest.mark.asyncio
async def test_wp_url_encodes_special_chars() -> None:
    """Page titles with parentheses/spaces are URL-encoded correctly."""
    adapter = _wp_adapter()

    search_json = {
        "batchcomplete": "",
        "query": {
            "search": [
                {
                    "title": "C++",
                    "pageid": 20001,
                    "snippet": "C++ programming language.",
                },
            ]
        },
    }
    extract_json = {
        "query": {
            "pages": {
                "20001": {
                    "pageid": 20001,
                    "title": "C++",
                    "extract": "C++ is a general-purpose programming language.",
                }
            }
        },
    }

    mocks = [_make_json_mock(search_json), _make_json_mock(extract_json)]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("C++")

    assert len(results) == 1
    # quote_plus replaces spaces with '+' and encodes special chars.
    assert "C%2B%2B" in results[0].url


@pytest.mark.asyncio
async def test_wp_non_english_language() -> None:
    """When language='it', the API and article URLs use it.wikipedia.org."""
    adapter = _wp_adapter(language="it")

    search_json = {
        "batchcomplete": "",
        "query": {
            "search": [
                {
                    "title": "Apprendimento profondo",
                    "pageid": 55102,
                    "snippet": "L'apprendimento profondo è una classe di metodi.",
                },
            ]
        },
    }
    extract_json = {
        "query": {
            "pages": {
                "55102": {
                    "pageid": 55102,
                    "title": "Apprendimento profondo",
                    "extract": "L'apprendimento profondo (deep learning) è una classe di metodi di apprendimento automatico.",
                }
            }
        },
    }

    mocks = [_make_json_mock(search_json), _make_json_mock(extract_json)]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("apprendimento profondo")

    assert len(results) == 1
    assert results[0].title == "Apprendimento profondo"
    assert "it.wikipedia.org" in results[0].url
    assert "metodi" in results[0].content


@pytest.mark.asyncio
async def test_wp_content_truncated_to_8000() -> None:
    """WikipediaAdapter caps page content at 8000 chars."""
    long_extract = "X " * 5000  # ~10000 chars
    search_json = {
        "batchcomplete": "",
        "query": {
            "search": [
                {
                    "title": "Long article",
                    "pageid": 90001,
                    "snippet": "S " * 300,
                },
            ]
        },
    }
    extract_json = {
        "query": {
            "pages": {
                "90001": {
                    "pageid": 90001,
                    "title": "Long article",
                    "extract": long_extract,
                }
            }
        },
    }

    adapter = _wp_adapter()
    mocks = [_make_json_mock(search_json), _make_json_mock(extract_json)]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("long")

    assert len(results) == 1
    assert len(results[0].content) <= 8000


@pytest.mark.asyncio
async def test_wp_result_is_searchresult_type() -> None:
    """Verify returned objects are SearchResult instances."""
    adapter = _wp_adapter(max_results=1)

    mocks = [
        _make_json_mock(_WP_SEARCH_JSON),
        _make_json_mock(_WP_EXTRACT_11001),
    ]

    with patch("httpx.AsyncClient", return_value=_mock_httpx_with_side_effect(mocks)):
        results = await adapter.search("deep learning")

    assert len(results) == 1
    assert isinstance(results[0], SearchResult)
