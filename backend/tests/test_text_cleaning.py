"""Tests for text_cleaning: select_relevant_chunks, split_into_chunks,
outline_terms, and strip_recurring_lines."""

from app.services.text_cleaning import (
    outline_terms,
    select_relevant_chunks,
    split_into_chunks,
    strip_recurring_lines,
)

# ── split_into_chunks ─────────────────────────────────────────────────────


def test_split_empty():
    assert split_into_chunks("", 1000) == []
    assert split_into_chunks("  \n  ", 1000) == []


def test_split_smaller_than_target():
    text = "Short text"
    assert split_into_chunks(text, 1000) == [text]


def test_split_on_paragraph_breaks():
    text = "Para 1.\n\nPara 2.\n\nPara 3."
    chunks = split_into_chunks(text, 20)
    assert len(chunks) >= 2


def test_split_preserves_content():
    text = "A" * 100 + "\n\n" + "B" * 100
    chunks = split_into_chunks(text, 80)
    combined = "".join(chunks)
    assert "A" * 100 in combined
    assert "B" * 100 in combined


# ── outline_terms ─────────────────────────────────────────────────────────


def test_outline_terms_extracts_tokens():
    terms = outline_terms(
        "Machine Learning Introduction",
        {
            "punti": ["Definizione di machine learning", "Paradigmi"],
        },
    )
    assert any("machine" in t for t in terms)
    assert any("learning" in t for t in terms)
    assert any("introduction" in t for t in terms)


def test_outline_terms_skips_stopwords():
    terms = outline_terms("the and for with that this", {})
    # All stopwords should be filtered out
    assert not any(t in {"the", "and", "for", "with", "that", "this"} for t in terms)


def test_outline_terms_handles_empty_outline():
    terms = outline_terms("Title", {})
    assert len(terms) >= 1  # at least the title tokens


# ── select_relevant_chunks ────────────────────────────────────────────────


def test_select_empty():
    assert select_relevant_chunks("", [], 1000) == ""
    assert select_relevant_chunks("  ", [], 1000) == ""


def test_select_small_text():
    text = "Short text about machine learning"
    result = select_relevant_chunks(text, ["machine", "learning"], 1000)
    assert result == text  # smaller than budget, returns all


def test_select_truncates_on_budget():
    long_text = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 100
    result = select_relevant_chunks(long_text, [], 50)
    assert len(result) <= 100  # budget includes some overhead


def test_select_prioritizes_relevant():
    # Make text LONGER than budget so the scoring path actually runs
    filler = "Irrelevant filler text that should be cut for budget. " * 20
    text = f"{filler}\n\nThe key concept is machine learning.\n\n{filler}"
    # Budget is smaller than full text — scoring path must select best chunks
    result = select_relevant_chunks(text, ["machine", "learning"], 500)
    assert "machine learning" in result, (
        "Relevant chunk with 'machine learning' must be selected over filler"
    )


def test_select_no_query_terms():
    text = "First chunk.\n\nSecond chunk.\n\nThird chunk."
    result = select_relevant_chunks(text, [], 15)
    # No query signal: keeps leading passages up to budget
    assert "First" in result


# ── strip_recurring_lines ─────────────────────────────────────────────────


def test_strip_short_document_unchanged():
    pages = ["Page 1\nHeader\nContent", "Page 2\nHeader\nContent"]
    result = strip_recurring_lines(pages, min_pages=4)
    assert result == pages  # too few pages, no-op


def test_strip_recurring_header():
    pages = [
        "Header\nThe capital of France is Paris",
        "Header\nThe capital of Italy is Rome",
        "Header\nThe capital of Germany is Berlin",
        "Header\nThe capital of Spain is Madrid",
        "Header\nThe capital of Portugal is Lisbon",
    ]
    result = strip_recurring_lines(pages, min_ratio=0.6, min_pages=3)
    for r in result:
        assert "Header" not in r
        assert "capital" in r


def test_strip_preserves_unique_content():
    pages = [
        "Header\nFirst unique thought about cats",
        "Header\nSecond unique thought about dogs",
        "Header\nThird unique thought about birds",
        "Header\nFourth unique thought about fish",
        "Header\nFifth unique thought about horses",
    ]
    result = strip_recurring_lines(pages, min_ratio=0.6, min_pages=3)
    for r in result:
        assert "unique" in r
