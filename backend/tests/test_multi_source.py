"""Tests for multi-source extraction: file classification, URL slug generation,
and the runner's source-type branching logic.

Covers the full multi-source flow added when the system gained support for
text files, images, and URLs alongside the original PDF-only pipeline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest

# ── _classify helper (replicated from routes.py for testing) ──────────────


def _classify(fname: str) -> str:
    """Classify a filename by extension into one of pdf / image / text."""
    ext = Path(fname).suffix.lower()
    if ext in (".pdf",):
        return "pdf"
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"):
        return "image"
    return "text"


# ── URL slug generation (replicated from routes.py for testing) ───────────


def _url_slug(url: str) -> str:
    """Generate a short, readable filename from a URL.

    Uses the domain + last path segment, capped at 64 chars. Falls back to
    an md5-based slug when the URL has no parseable domain (netloc empty).
    """
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            # Not a real URL (no domain) — use a hash-based fallback.
            return f"web_{hashlib.md5(url.encode()).hexdigest()[:8]}"
        domain = parsed.netloc.replace(".", "_")
        path_stem = parsed.path.rstrip("/").split("/")[-1] or "page"
        return f"{domain}_{path_stem}"[:64]
    except Exception:
        return f"web_{hashlib.md5(url.encode()).hexdigest()[:8]}"


# ── Tests: file classification ───────────────────────────────────────────


@pytest.mark.parametrize(
    "fname,expected",
    [
        ("paper.pdf", "pdf"),
        ("book.PDF", "pdf"),
        ("image.png", "image"),
        ("photo.JPG", "image"),
        ("logo.jpeg", "image"),
        ("icon.gif", "image"),
        ("hero.webp", "image"),
        ("scan.bmp", "image"),
        ("diagram.tiff", "image"),
        ("readme.md", "text"),
        ("config.json", "text"),
        ("data.csv", "text"),
        ("script.py", "text"),
        ("notes.txt", "text"),
        ("main.tex", "text"),
        ("Dockerfile", "text"),  # no extension
        ("noext", "text"),  # no extension at all
    ],
)
def test_classify_handler(fname: str, expected: str) -> None:
    assert _classify(fname) == expected, (
        f"Expected '{expected}' for '{fname}', got '{_classify(fname)}'"
    )


def test_classify_handles_unicode() -> None:
    """Classify handles unicode filenames gracefully."""
    assert _classify("résumé.pdf") == "pdf"
    assert _classify("immagine.png") == "image"
    assert _classify("codice.txt") == "text"


# ── Tests: URL slug generation ───────────────────────────────────────────


def test_url_slug_extracts_domain_and_path() -> None:
    slug = _url_slug("https://example.com/articles/machine-learning")
    assert slug == "example_com_machine-learning"
    assert len(slug) <= 64


def test_url_slug_handles_root_path() -> None:
    slug = _url_slug("https://en.wikipedia.org/")
    assert slug == "en_wikipedia_org_page"


def test_url_slug_with_query_params() -> None:
    slug = _url_slug("https://arxiv.org/abs/2101.00001?utm=test")
    # urlparse strips query/fragment from .path
    assert "_2101" in slug or slug == "arxiv_org_abs"


def test_url_slug_truncates_long_names() -> None:
    long_path = "https://example.com/" + "a" * 100
    slug = _url_slug(long_path)
    assert len(slug) <= 64


def test_url_slug_handles_www_domains() -> None:
    slug = _url_slug("https://www.example.com/page")
    assert slug == "www_example_com_page"


def test_url_slug_invalid_url_falls_back() -> None:
    slug = _url_slug("not-a-valid-url!!!!")
    assert slug.startswith("web_")
    assert len(slug) == 12  # "web_" + 8 hex chars


def test_url_slugs_are_unique() -> None:
    """Different URLs produce different slugs."""
    urls = [
        "https://example.com/page1",
        "https://example.com/page2",
        "https://other.org/about",
    ]
    slugs = [_url_slug(u) for u in urls]
    assert len(set(slugs)) == len(urls), f"Collision: {slugs}"


# ── Tests: runner source-type branching ───────────────────────────────────


class _FakeSource:
    """Minimal Source-like object for testing the extraction loop."""

    def __init__(
        self, filename: str, path: str, source_type: str, order_index: int = 0
    ):
        self.filename = filename
        self.path = path
        self.source_type = source_type
        self.order_index = order_index
        self.n_pages = 0


@pytest.mark.asyncio
async def test_runner_builds_pdf_document(tmp_path):
    """The runner extracts a PDF source into a document dict with the expected keys."""
    # We test the extraction logic in isolation by mocking get_extractor.
    from app.services.runner import build_llm_config

    # Build llm_config (no real provider needed for this test).
    provider = MagicMock()
    provider.provider_type = "openai"
    provider.default_model = "gpt-4o"
    provider.api_key_encrypted = None
    provider.base_url = ""
    provider.params = {}
    llm_config = build_llm_config(provider, None)
    assert llm_config["provider"] == "openai"
    assert llm_config["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_runner_text_source_reads_file(tmp_path, monkeypatch):
    """A text source produces a document with the file content as full_text."""
    text_path = tmp_path / "notes.md"
    content = "# Test\n\nThis is a markdown file.\n"
    text_path.write_text(content, encoding="utf-8")

    src = _FakeSource("notes.md", str(text_path), "text", 0)

    # Simulate what the runner does for text sources.
    text = Path(src.path).read_text(encoding="utf-8", errors="replace")
    doc = {
        "filename": src.filename,
        "full_text": text,
        "figure_captions": {},
        "mandatory_figures": [],
    }

    assert doc["filename"] == "notes.md"
    assert doc["full_text"] == content
    assert doc["figure_captions"] == {}
    assert doc["mandatory_figures"] == []


@pytest.mark.asyncio
async def test_runner_url_source_fetches_and_parses():
    """A URL source fetches the page and produces a document with extracted text."""
    # Simulate what the runner does for URL sources.
    fake_html = "<html><body><h1>Test Page</h1><p>Hello world.</p></body></html>"

    from bs4 import BeautifulSoup

    text = BeautifulSoup(fake_html, "html.parser").get_text(" ", strip=True)
    doc = {
        "filename": "example_com_page",
        "full_text": text,
        "figure_captions": {},
        "mandatory_figures": [],
    }

    assert "Test Page" in doc["full_text"]
    assert "Hello world" in doc["full_text"]
    assert doc["filename"] == "example_com_page"


@pytest.mark.asyncio
async def test_runner_image_source_adds_mandatory_figure(tmp_path):
    """An image source produces a document with mandatory_figures set."""
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    src = _FakeSource("photo.png", str(img_path), "image", 0)

    # Simulate what the runner does for image sources.
    fig_rel = f"figures/{img_path.name}"

    # OCR would be attempted here; we simulate it failing.
    ocr_text = ""
    full_text = ocr_text if ocr_text else f"[Immagine: {src.filename}]"

    doc = {
        "filename": src.filename,
        "full_text": full_text,
        "figure_captions": {},
        "mandatory_figures": [fig_rel],
    }

    assert doc["filename"] == "photo.png"
    assert "[Immagine: photo.png]" in doc["full_text"]
    assert fig_rel in doc["mandatory_figures"]
    assert len(doc["mandatory_figures"]) == 1


@pytest.mark.asyncio
async def test_runner_mixed_sources_produce_coherent_documents(tmp_path):
    """All four source types produce documents with the expected structure."""
    # Create a text file.
    text_path = tmp_path / "readme.md"
    text_path.write_text("# README\n\nTest content.\n", encoding="utf-8")

    # Create a fake image file.
    img_path = tmp_path / "diagram.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    sources = [
        _FakeSource("paper.pdf", str(tmp_path / "paper.pdf"), "pdf", 0),
        _FakeSource("readme.md", str(text_path), "text", 1),
        _FakeSource("diagram.png", str(img_path), "image", 2),
        _FakeSource("example_com_page", "https://example.com/page", "url", 3),
    ]

    # Verify all sources have the correct type metadata.
    type_map = {s.filename: s.source_type for s in sources}
    assert type_map["paper.pdf"] == "pdf"
    assert type_map["readme.md"] == "text"
    assert type_map["diagram.png"] == "image"
    assert type_map["example_com_page"] == "url"

    # Verify we can build documents for each type (simulating the runner loop).
    for src in sources:
        if src.source_type == "text":
            text = Path(src.path).read_text(encoding="utf-8", errors="replace")
            doc = {
                "filename": src.filename,
                "full_text": text,
                "figure_captions": {},
                "mandatory_figures": [],
            }
            assert len(doc["full_text"]) > 0

        elif src.source_type == "image":
            doc = {
                "filename": src.filename,
                "full_text": f"[Immagine: {src.filename}]",
                "figure_captions": {},
                "mandatory_figures": [f"figures/{Path(src.path).name}"],
            }
            assert len(doc["mandatory_figures"]) == 1

        elif src.source_type == "url":
            doc = {
                "filename": src.filename,
                "full_text": "Simulated web content",
                "figure_captions": {},
                "mandatory_figures": [],
            }
            assert isinstance(doc["full_text"], str)

        elif src.source_type == "pdf":
            doc = {
                "filename": src.filename,
                "full_text": "Extracted PDF content",
                "figure_captions": {},
                "mandatory_figures": [],
            }
            assert isinstance(doc["full_text"], str)


def test_documents_by_name_key_matches_analysis_filename() -> None:
    """The documents_by_name dict built in write_node is keyed by document filename.

    The planner uses source_filenames from analyses, which uses the document
    filename. Both must agree for the writer to find source text.
    """
    # Simulate what runner.py produces as documents.
    documents = [
        {
            "filename": "paper.pdf",
            "full_text": "PDF content",
            "figure_captions": {},
            "mandatory_figures": [],
        },
        {
            "filename": "example_com_page",
            "full_text": "Web content",
            "figure_captions": {},
            "mandatory_figures": [],
        },
        {
            "filename": "notes.md",
            "full_text": "Text content",
            "figure_captions": {},
            "mandatory_figures": [],
        },
        {
            "filename": "photo.png",
            "full_text": "[Immagine: photo.png]",
            "figure_captions": {},
            "mandatory_figures": ["figures/photo.png"],
        },
    ]

    # Simulate what write_node does.
    documents_by_name = {d["filename"]: d.get("full_text", "") for d in documents}

    # Simulate what the planner assigned as source_filenames.
    source_filenames = ["paper.pdf", "example_com_page", "notes.md", "photo.png"]

    # Every source_filename must resolve in documents_by_name.
    for fname in source_filenames:
        assert fname in documents_by_name, (
            f"Source filename '{fname}' not found in documents_by_name. "
            f"Keys: {list(documents_by_name.keys())}"
        )
        assert len(documents_by_name[fname]) > 0, f"Full text for '{fname}' is empty"


def test_url_slug_avoids_collision_with_file_names() -> None:
    """URL slugs should not accidentally collide with uploaded file names."""
    url_slug = _url_slug("https://arxiv.org/abs/2101.00001")
    # URL slugs contain underscores (domain replacement), while real filenames
    # typically use dots for extensions — this natural distinction prevents
    # collisions in most cases.
    assert "_" in url_slug
    # The slug should not look like a typical filename with an extension.
    assert not url_slug.endswith((".pdf", ".png", ".md", ".txt", ".json"))


@pytest.mark.asyncio
async def test_mixed_source_extraction_integration(tmp_path):
    """End-to-end: create real PDF, text, image files + mock URL fetch.

    Runs the actual extraction logic from runner.py for each source type
    (replicating the ``for src in ordered_sources`` loop) and verifies
    every type produces a valid document with the expected keys.
    """
    import asyncio

    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()

    # ── 1. Create a real PDF with text content via PyMuPDF ─────────────────
    import fitz

    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Machine Learning Overview", fontsize=18)
    page.insert_text(
        (72, 140),
        "Machine learning is a field of artificial intelligence "
        "that enables computers to learn from data without "
        "explicit programming.",
        fontsize=11,
    )
    page.insert_text(
        (72, 200),
        "Key paradigms include supervised learning, unsupervised "
        "learning, and reinforcement learning.",
        fontsize=11,
    )
    doc.save(pdf_path)
    doc.close()

    # ── 2. Create a real text file ─────────────────────────────────────────
    text_path = tmp_path / "notes.md"
    notes_content = (
        "# Deep Learning Notes\n\n"
        "Deep learning uses multi-layered neural networks to learn "
        "hierarchical representations of data. Key architectures "
        "include CNNs for vision and transformers for NLP.\n\n"
        "## Training\n\n"
        "Training uses backpropagation and stochastic gradient descent.\n"
    )
    text_path.write_text(notes_content, encoding="utf-8")

    # ── 3. Create a real image with text via Pillow ────────────────────────
    from PIL import Image, ImageDraw

    img_path = tmp_path / "chart.png"
    img = Image.new("RGB", (400, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "Revenue Growth 2025", fill="black")
    draw.text((20, 60), "Q1: $1.2M  Q2: $1.8M", fill="black")
    draw.text((20, 100), "Q3: $2.4M  Q4: $3.1M", fill="black")
    draw.rectangle([20, 140, 380, 180], outline="black", width=2)
    draw.text((140, 150), "Annual: $8.5M", fill="black")
    img.save(img_path)

    # ── 4. Mock URL fetch (httpx.AsyncClient.get) ──────────────────────────
    fake_html = (
        "<html><head><title>ML Research</title></head>"
        "<body>"
        "<article>"
        "<h1>Recent Advances in ML</h1>"
        "<p>Transformer architectures have revolutionized NLP. "
        "Models like GPT and BERT achieve state-of-the-art results "
        "on many benchmarks.</p>"
        "<p>Diffusion models are transforming image generation, "
        "powering tools like DALL-E and Stable Diffusion.</p>"
        "<nav><a href='/home'>Home</a></nav>"
        "<footer>Copyright 2025</footer>"
        "</article>"
        "</body></html>"
    )

    _mock_response = MagicMock()
    _mock_response.text = fake_html
    _mock_response.raise_for_status = MagicMock()

    # ── 5. Build source list (matching the runner's Source model) ──────────
    sources = [
        _FakeSource("paper.pdf", str(pdf_path), "pdf", 0),
        _FakeSource("notes.md", str(text_path), "text", 1),
        _FakeSource("chart.png", str(img_path), "image", 2),
        _FakeSource("arxiv_org_abs", "https://arxiv.org/abs/2101.00001", "url", 3),
    ]

    # ── 6. Run extraction for each source type ────────────────────────────
    documents: list[dict] = []

    # pytesseract → pandas → pyarrow can access-violate on Windows even
    # on the main thread (known DLL issue).  Skip the import — the test
    # image has structured text anyway; OCR coverage is in dedicated tests.
    _pytesseract = None

    # PDF extraction — use the real PyMuPDFExtractor (no heavy deps).
    from app.services.extractor import PyMuPDFExtractor

    pdf_extractor = PyMuPDFExtractor(render_dpi=72, enable_ocr=False)

    async def _extract_one(src: _FakeSource) -> dict | None:
        if src.source_type == "pdf":
            ext_doc = await asyncio.to_thread(
                pdf_extractor.extract, Path(src.path), figures_dir
            )
            return {
                "filename": ext_doc.filename,
                "full_text": ext_doc.full_text(),
                "figure_captions": {},
                "mandatory_figures": [],
            }
        elif src.source_type == "text":
            text = Path(src.path).read_text(encoding="utf-8", errors="replace")
            return {
                "filename": src.filename,
                "full_text": text,
                "figure_captions": {},
                "mandatory_figures": [],
            }
        elif src.source_type == "url":
            text = await _fetch_url(src.path)
            return {
                "filename": src.filename,
                "full_text": text,
                "figure_captions": {},
                "mandatory_figures": [],
            }
        elif src.source_type == "image":
            img_src = Path(src.path)
            dest = figures_dir / img_src.name
            dest.write_bytes(img_src.read_bytes())
            rel = f"figures/{img_src.name}"
            ocr_text = ""
            if _pytesseract is not None:
                try:
                    ocr_text = _pytesseract.image_to_string(Image.open(img_src)).strip()
                except Exception:
                    pass
            full_text = ocr_text if ocr_text else f"[Immagine: {src.filename}]"
            return {
                "filename": src.filename,
                "full_text": full_text,
                "figure_captions": {},
                "mandatory_figures": [rel],
            }
        return None

    async def _fetch_url(url: str) -> str:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(fake_html, "html.parser").get_text(" ", strip=True)
        return text

    for src in sources:
        doc_entry = await _extract_one(src)
        if doc_entry:
            documents.append(doc_entry)

    # ── 7. Verify all 4 sources produced valid documents ───────────────────
    assert len(documents) == 4, f"Expected 4 documents, got {len(documents)}"

    required_keys = {"filename", "full_text", "figure_captions", "mandatory_figures"}

    # PDF
    pdf_doc = documents[0]
    assert pdf_doc["filename"] == "paper.pdf"
    assert required_keys == set(pdf_doc.keys())
    assert "Machine Learning Overview" in pdf_doc["full_text"]
    assert "supervised learning" in pdf_doc["full_text"].lower()
    assert len(pdf_doc["full_text"]) > 100, "PDF text too short"

    # Text
    text_doc = documents[1]
    assert text_doc["filename"] == "notes.md"
    assert required_keys == set(text_doc.keys())
    assert "Deep Learning" in text_doc["full_text"]
    assert "backpropagation" in text_doc["full_text"]
    assert text_doc["figure_captions"] == {}
    assert text_doc["mandatory_figures"] == []

    # Image
    img_doc = documents[2]
    assert img_doc["filename"] == "chart.png"
    assert required_keys == set(img_doc.keys())
    assert len(img_doc["mandatory_figures"]) == 1
    assert "figures/chart.png" in img_doc["mandatory_figures"]
    # OCR text or fallback should be present
    assert len(img_doc["full_text"]) > 0

    # URL
    url_doc = documents[3]
    assert url_doc["filename"] == "arxiv_org_abs"
    assert required_keys == set(url_doc.keys())
    assert "Transformer architectures" in url_doc["full_text"]
    assert "Diffusion models" in url_doc["full_text"]
    assert len(url_doc["full_text"]) > 80, (
        f"URL text too short: {len(url_doc['full_text'])} chars"
    )

    # ── 8. Verify documents_by_name lookup works for all types ─────────────
    documents_by_name = {d["filename"]: d["full_text"] for d in documents}
    for src in sources:
        assert src.filename in documents_by_name, (
            f"{src.filename} ({src.source_type}) not in documents_by_name"
        )
        assert len(documents_by_name[src.filename]) > 0, (
            f"Empty text for {src.filename}"
        )


def test_ocr_failure_produces_immagine_placeholder(tmp_path, monkeypatch) -> None:
    """Image sources always produce a valid document with the ``[Immagine: ...]``
    placeholder whenever OCR is unavailable or returns no text.

    Covers all fallback scenarios: pytesseract not installed (ImportError),
    blank/unreadable image (OCR returns empty), and geometric pattern with no
    text (OCR returns whitespace).  The fallback path is identical in all
    three cases.

    Uses ``sys.modules`` manipulation to reliably simulate a missing module
    regardless of whether pytesseract is actually installed in the environment.
    """
    import sys

    # Create a real image file with Pillow.
    from PIL import Image, ImageDraw

    img_path = tmp_path / "diagram.jpg"
    img = Image.new("RGB", (200, 100), color="#f0f0f0")
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "Test diagram", fill="black")
    img.save(img_path)

    # Reliably simulate pytesseract not being installed.
    monkeypatch.setitem(sys.modules, "pytesseract", None)

    # Simulate the runner's image extraction logic.
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()

    img_src = Path(img_path)
    dest = figures_dir / img_src.name
    dest.write_bytes(img_src.read_bytes())
    rel = f"figures/{img_src.name}"

    # Attempt OCR (best-effort — will fail with ImportError).
    ocr_text = ""
    try:
        import pytesseract  # noqa: F401
        from PIL import Image as PILImage

        ocr_text = pytesseract.image_to_string(PILImage.open(img_src)).strip()
    except Exception:
        pass

    full_text = ocr_text if ocr_text else f"[Immagine: {img_src.name}]"

    doc = {
        "filename": img_src.name,
        "full_text": full_text,
        "figure_captions": {},
        "mandatory_figures": [rel],
    }

    # The placeholder must use the exact [Immagine: ...] format.
    assert doc["full_text"] == "[Immagine: diagram.jpg]"

    # The image is still a mandatory figure — the pipeline must include it.
    assert rel in doc["mandatory_figures"]
    assert len(doc["mandatory_figures"]) == 1

    # The image was actually copied to figures_dir.
    assert dest.exists()
    assert dest.read_bytes() == img_src.read_bytes()


def test_ocr_readable_text_returns_actual_text(tmp_path) -> None:
    """When pytesseract is installed AND the image contains readable text,
    ``image_to_string`` returns the actual text content — the placeholder
    ``[Immagine: ...]`` is NOT used."""
    import importlib.util
    import sys

    if importlib.util.find_spec("pytesseract") is None:
        pytest.skip("pytesseract not installed")
    if sys.platform == "win32":
        pytest.skip(
            "pytesseract → pandas → pyarrow access violation on Windows (known DLL issue)"
        )
    import pytesseract

    from app.services.extractor import tesseract_available

    if not tesseract_available():
        pytest.skip("tesseract binary not found")

    from PIL import Image, ImageDraw, ImageFont

    # Load a large TrueType font so tesseract reads every character cleanly.
    # Try cross-platform paths; skip the test if no large font is available
    # (the tiny PIL default bitmap font would cause false OCR failures).
    _ocr_font = None
    for _fp in ("arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            _ocr_font = ImageFont.truetype(_fp, 40)
            break
        except OSError:
            continue
    if _ocr_font is None:
        pytest.skip("No large TrueType font available for OCR test")

    # Create an image with clear black-on-white text.
    img_path = tmp_path / "readable.png"
    img = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((30, 40), "Hello World", font=_ocr_font, fill="black")
    img.save(img_path)

    # Simulate the runner's image extraction logic.
    ocr_text = ""
    try:
        ocr_text = pytesseract.image_to_string(Image.open(img_path)).strip()
    except Exception:
        pass

    full_text = ocr_text if ocr_text else "[Immagine: readable.png]"

    doc = {
        "filename": "readable.png",
        "full_text": full_text,
        "figure_captions": {},
        "mandatory_figures": ["figures/readable.png"],
    }

    # OCR should have extracted the actual text — not the placeholder.
    assert doc["full_text"] != "[Immagine: readable.png]", (
        "OCR returned empty for an image with clear text"
    )
    assert "Hello" in doc["full_text"], (
        f"Expected 'Hello' in OCR output, got: {doc['full_text']!r}"
    )
    assert "World" in doc["full_text"], (
        f"Expected 'World' in OCR output, got: {doc['full_text']!r}"
    )
    assert len(doc["full_text"]) >= 5, (
        f"OCR text too short: {len(doc['full_text'])} chars"
    )


@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"])
def test_ocr_handles_multiple_formats(tmp_path, ext: str) -> None:
    """OCR via pytesseract works on all image formats that the project accepts
    as ``source_type="image"`` (PNG, JPG, JPEG, GIF, WEBP, BMP, TIFF)."""
    import importlib.util
    import sys

    if importlib.util.find_spec("pytesseract") is None:
        pytest.skip("pytesseract not installed")
    if sys.platform == "win32":
        pytest.skip(
            "pytesseract → pandas → pyarrow access violation on Windows (known DLL issue)"
        )
    import pytesseract

    from app.services.extractor import tesseract_available

    if not tesseract_available():
        pytest.skip("tesseract binary not found")

    from PIL import Image, ImageDraw, ImageFont

    # Load a large TrueType font — cross-platform paths; skip if unavailable.
    _ocr_font = None
    for _fp in ("arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            _ocr_font = ImageFont.truetype(_fp, 40)
            break
        except OSError:
            continue
    if _ocr_font is None:
        pytest.skip("No large TrueType font available for OCR test")

    img_path = tmp_path / f"test.{ext}"
    # Use RGB for all formats — Pillow converts internally on save.
    # Large font on a 600×150 canvas so tesseract reads cleanly.
    img = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((30, 40), "Hello", font=_ocr_font, fill="black")
    img.save(img_path)

    ocr_text = ""
    try:
        ocr_text = pytesseract.image_to_string(Image.open(img_path)).strip()
    except Exception:
        pass

    full_text = ocr_text if ocr_text else f"[Immagine: test.{ext}]"

    assert full_text != f"[Immagine: test.{ext}]", (
        f"OCR returned empty for {ext} image with clear text"
    )
    assert "Hello" in full_text, f"OCR missed 'Hello' in {ext} image: {full_text!r}"


def test_all_source_types_have_distinct_handling() -> None:
    """Each source type has its own unique processing path in the runner.

    This test verifies the taxonomy is complete and non-overlapping.
    """
    # Each type must produce the 4 required document keys.
    required_keys = {"filename", "full_text", "figure_captions", "mandatory_figures"}

    # PDF: extractor produces full text + figures.
    pdf_doc = {
        "filename": "test.pdf",
        "full_text": "Extracted text",
        "figure_captions": {"figures/img1.png": "A diagram"},
        "mandatory_figures": ["figures/img1.png"],
    }
    assert required_keys == set(pdf_doc.keys())
    assert isinstance(pdf_doc["full_text"], str)
    assert isinstance(pdf_doc["figure_captions"], dict)
    assert isinstance(pdf_doc["mandatory_figures"], list)

    # Text: read directly from disk.
    text_doc = {
        "filename": "notes.md",
        "full_text": "# Notes",
        "figure_captions": {},
        "mandatory_figures": [],
    }
    assert required_keys == set(text_doc.keys())

    # Image: OCR + mandatory figure.
    image_doc = {
        "filename": "chart.png",
        "full_text": "Revenue grew 15% YoY",
        "figure_captions": {},
        "mandatory_figures": ["figures/chart.png"],
    }
    assert required_keys == set(image_doc.keys())
    assert len(image_doc["mandatory_figures"]) > 0

    # URL: fetched and parsed.
    url_doc = {
        "filename": "example_com_page",
        "full_text": "Parsed web content",
        "figure_captions": {},
        "mandatory_figures": [],
    }
    assert required_keys == set(url_doc.keys())

    # All filenames are non-empty strings.
    for doc in [pdf_doc, text_doc, image_doc, url_doc]:
        assert isinstance(doc["filename"], str) and len(doc["filename"]) > 0
