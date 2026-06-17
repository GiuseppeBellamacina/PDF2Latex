"""Tests for bibliography: consolidate, cited_keys, build_bib, strip functions."""

from app.services.bibliography import (
    bibtex_entry,
    build_bib,
    cited_keys,
    consolidate_references,
    make_key,
    strip_inline_bibliography,
    strip_unknown_citations,
)

# ── consolidate_references ────────────────────────────────────────────────


def test_consolidate_empty():
    assert consolidate_references([]) == []


def test_consolidate_single_ref():
    refs = [
        (
            "paper.pdf",
            [{"authors": "Rossi and Bianchi", "title": "Titolo", "year": "2023"}],
        )
    ]
    result = consolidate_references(refs)
    assert len(result) == 1
    assert result[0]["source_filename"] == "paper.pdf"
    assert result[0]["authors"] == "Rossi and Bianchi"
    assert "key" in result[0]
    assert len(result[0]["key"]) > 0


def test_consolidate_deduplicates():
    refs = [
        ("a.pdf", [{"title": "Duplicate", "authors": "A", "year": "2020"}]),
        ("b.pdf", [{"title": "Duplicate", "authors": "A", "year": "2020"}]),
    ]
    result = consolidate_references(refs)
    assert len(result) == 1  # deduplicated


def test_consolidate_skips_empty():
    refs = [
        ("a.pdf", [{"title": "", "authors": ""}]),  # both empty → skip
        ("b.pdf", [{"title": "Valid", "authors": "B"}]),
    ]
    result = consolidate_references(refs)
    assert len(result) == 1
    assert result[0]["title"] == "Valid"


# ── make_key ──────────────────────────────────────────────────────────────


def test_make_key_from_author_year():
    used: set[str] = set()
    key = make_key(
        {"authors": "Rossi and Bianchi", "year": "2023", "title": "Some Paper"}, used
    )
    assert "rossi" in key.lower()
    assert "2023" in key


def test_make_key_deduplicates():
    used: set[str] = set()
    k1 = make_key({"authors": "Rossi", "year": "2023"}, used)
    k2 = make_key({"authors": "Rossi", "year": "2023"}, used)
    assert k1 != k2  # second gets suffix 'a'
    assert k2.endswith("a")


# ── bibtex_entry ──────────────────────────────────────────────────────────


def test_bibtex_entry_format():
    ref = {
        "key": "rossi2023",
        "authors": "Rossi and Bianchi",
        "title": "Paper Title",
        "year": "2023",
        "venue": "Journal",
    }
    entry = bibtex_entry(ref)
    assert "@article{" in entry
    assert "rossi2023" in entry
    assert "Rossi" in entry
    assert "Paper Title" in entry
    assert "2023" in entry


def test_bibtex_entry_misc_no_venue():
    ref = {"key": "anon", "authors": "Author", "title": "Title"}
    entry = bibtex_entry(ref)
    assert "@misc{" in entry


# ── cited_keys ────────────────────────────────────────────────────────────


def test_cited_keys_extracts():
    latex = r"\cite{key1,key2} and \citep{key3} and \parencite[see]{key4}"
    keys = cited_keys(latex)
    assert keys == {"key1", "key2", "key3", "key4"}


def test_cited_keys_empty():
    assert cited_keys("") == set()
    assert cited_keys("No citations here.") == set()


# ── build_bib ─────────────────────────────────────────────────────────────


def test_build_bib_all():
    pool = [
        {"key": "a", "authors": "A", "title": "T1", "year": "2020"},
        {"key": "b", "authors": "B", "title": "T2", "year": "2021"},
    ]
    result = build_bib(pool)
    assert "@article" in result or "@misc" in result
    assert "a" in result
    assert "b" in result


def test_build_bib_filtered():
    pool = [
        {"key": "a", "authors": "A", "title": "T1"},
        {"key": "b", "authors": "B", "title": "T2"},
    ]
    result = build_bib(pool, keys={"a"})
    assert "a" in result
    assert "b" not in result  # filtered out


# ── strip functions ───────────────────────────────────────────────────────


def test_strip_unknown_citations():
    latex = r"\cite{known1,unknown,known2}"
    result = strip_unknown_citations(latex, {"known1", "known2"})
    assert "known1" in result
    assert "known2" in result
    assert "unknown" not in result


def test_strip_unknown_citations_all_unknown():
    latex = r"\cite{unknown}"
    result = strip_unknown_citations(latex, {"known"})
    assert result.strip() == ""


def test_strip_inline_bibliography():
    latex = (
        r"\section{Test}"
        r"\begin{thebibliography}{99}"
        r"\bibitem{key} Entry"
        r"\end{thebibliography}"
        r"\section{After}"
    )
    result = strip_inline_bibliography(latex)
    assert r"\begin{thebibliography}" not in result
    assert "Test" in result
    assert "After" in result


def test_strip_bib_commands():
    latex = r"\bibliographystyle{plain}\n\bibliography{refs}\nContent"
    result = strip_inline_bibliography(latex)
    assert r"\bibliographystyle" not in result
    assert r"\bibliography" not in result
    assert "Content" in result


def test_strip_unknown_citations_preserves_text():
    """Non-cite text is preserved even when citations are dropped."""
    latex = r"See \cite{unknown} for details."
    result = strip_unknown_citations(latex, {"known"})
    assert "See" in result
    assert "for details" in result
    assert "unknown" not in result
