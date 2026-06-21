"""Shared fixtures and helpers for the test suite."""

from __future__ import annotations

# ── Load .env.test BEFORE any app imports ─────────────────────────────────
# This populates os.environ with test credentials (PDF2TEX_TEST_*) so that
# real-LLM and real-web-tool fixtures pick them up.  Existing env vars are
# NOT overwritten, so CI and local overrides still take priority.
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_env_test = Path(__file__).resolve().parent.parent / ".env.test"
if _env_test.exists():
    load_dotenv(_env_test, override=False)

import json  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.agents.state import PlannedSection  # noqa: E402

# ── Markdown report plugin ────────────────────────────────────────────────
# Stores per-test results during the session and writes a README-style
# markdown report at session end.  Especially useful for sandbox tests.

_SANDBOX_REPORT: dict[str, list[dict]] = {}  # category → list of result dicts
_SANDBOX_WARNINGS: dict[str, list] = {}  # nodeid → list of warning messages
_SESSION_START: float = 0.0
_current_nodeid: str | None = None


def _sandbox_category(nodeid: str) -> str:
    """Map a test nodeid to a human-readable category."""
    if "ocr_" in nodeid:
        return "OCR"
    if "math_" in nodeid:
        return "Math"
    if "structure_" in nodeid:
        return "Structure"
    if "web_" in nodeid:
        return "Web Tools"
    if "llm_" in nodeid:
        return "LLM"
    return "Other"


def _md_escape(text: str) -> str:
    """Escape pipes and other sensitive chars for markdown tables."""
    return text.replace("|", "\\|").replace("\n", "<br>")


def _md_code(text: str, lang: str = "") -> str:
    """Wrap text in a markdown fenced code block, or inline if short."""
    if not text or not text.strip():
        return "`(empty)`"
    if len(text) < 120 and "\n" not in text:
        return f"`{_md_escape(text)}`"
    return f"\n```{lang}\n{text.strip()}\n```\n"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture test-phase results for the markdown report."""
    outcome = yield
    report = outcome.get_result()

    if not item.get_closest_marker("sandbox"):
        return
    if report.when != "call":
        return

    category = _sandbox_category(item.nodeid)
    if category not in _SANDBOX_REPORT:
        _SANDBOX_REPORT[category] = []

    # Prefer longreprtext (plain text) over longrepr (may be a repr object).
    longrepr = ""
    if hasattr(report, "longreprtext"):
        longrepr = report.longreprtext
    elif report.longrepr:
        longrepr = str(report.longrepr)

    entry: dict = {
        "name": item.name,
        "nodeid": item.nodeid,
        "outcome": report.outcome,
        "duration": report.duration,
        "longrepr": longrepr,
        "capstdout": report.capstdout if hasattr(report, "capstdout") else "",
        "capstderr": report.capstderr if hasattr(report, "capstderr") else "",
        "warnings": [],
    }

    # Collect warnings captured by pytest_warning_recorded for this nodeid.
    nodeid = item.nodeid
    warn_records = _SANDBOX_WARNINGS.pop(nodeid, [])
    if warn_records:
        entry["warnings"] = [
            f"{w.category.__name__}: {w.message}" for w in warn_records
        ]

    _SANDBOX_REPORT[category].append(entry)


def pytest_runtest_logstart(nodeid: str, location) -> None:
    """Track the current test nodeid for warning association."""
    global _current_nodeid
    _current_nodeid = nodeid


def pytest_warning_recorded(warning_message) -> None:
    """Store warnings keyed by the current test nodeid."""
    global _current_nodeid
    nodeid = getattr(warning_message, "nodeid", None) or _current_nodeid
    if nodeid is None:
        return
    _SANDBOX_WARNINGS.setdefault(nodeid, []).append(warning_message)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Generate a markdown report from collected sandbox test results."""
    if not _SANDBOX_REPORT:
        return

    report_path = Path(session.config.rootpath) / "report-sandbox.md"
    elapsed = time.monotonic() - _SESSION_START if _SESSION_START else 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    total = sum(len(v) for v in _SANDBOX_REPORT.values())
    passed = sum(
        1 for v in _SANDBOX_REPORT.values() for r in v if r["outcome"] == "passed"
    )
    failed = sum(
        1 for v in _SANDBOX_REPORT.values() for r in v if r["outcome"] == "failed"
    )
    skipped = sum(
        1 for v in _SANDBOX_REPORT.values() for r in v if r["outcome"] == "skipped"
    )

    lines: list[str] = []
    lines.append("# 📊 Sandbox Test Report")
    lines.append("")
    lines.append(f"**Generated**: {now}  ")
    lines.append(f"**Duration**: {elapsed:.1f}s  ")
    lines.append(
        f"**Tests**: {total} total  |  ✅ {passed} passed  |  ❌ {failed} failed  |  ⏭️ {skipped} skipped"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-category sections in a fixed order.
    cat_order = ["OCR", "Math", "Structure", "Web Tools", "LLM"]
    for cat in cat_order:
        entries = _SANDBOX_REPORT.get(cat, [])
        if not entries:
            continue

        cat_passed = sum(1 for e in entries if e["outcome"] == "passed")
        cat_failed = sum(1 for e in entries if e["outcome"] == "failed")
        cat_skipped = sum(1 for e in entries if e["outcome"] == "skipped")

        emoji = {
            "OCR": "🖼️",
            "Math": "🧮",
            "Structure": "📐",
            "Web Tools": "🌐",
            "LLM": "🤖",
        }.get(cat, "📋")
        lines.append(f"## {emoji} {cat}")
        lines.append("")
        lines.append("| Status | Test | Duration | Output |")
        lines.append("|:------:|:-----|---------:|:-------|")

        for e in entries:
            status_icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️"}.get(
                e["outcome"], "❓"
            )
            name = _md_escape(e["name"])
            duration = f"{e['duration']:.2f}s"

            # Build output cell.
            output_parts: list[str] = []
            if e["outcome"] == "failed" and e["longrepr"]:
                # Extract the last relevant assertion / error line.
                err = e["longrepr"].strip()
                # Truncate very long tracebacks.
                if len(err) > 600:
                    err = "…\n" + err[-500:]
                output_parts.append(f"**Error**: {_md_code(err, 'text')}")
            stdout = (e.get("capstdout") or "").strip()
            if stdout:
                output_parts.append(f"**stdout**: {_md_code(stdout[:500], 'text')}")
            stderr = (e.get("capstderr") or "").strip()
            if stderr:
                output_parts.append(f"**stderr**: {_md_code(stderr[:500], 'text')}")
            for w in e.get("warnings", []):
                output_parts.append(f"⚠️ `{_md_escape(w[:200])}`")

            output = "<br>".join(output_parts) if output_parts else "—"
            lines.append(f"| {status_icon} | {name} | {duration} | {output} |")

        lines.append("")
        lines.append(
            f"*{cat_passed} passed, {cat_failed} failed, {cat_skipped} skipped*"
        )
        lines.append("")

    # Footer with re-run instructions.
    lines.append("---")
    lines.append("")
    lines.append("### Re-run")
    lines.append("")
    lines.append("```bash")
    lines.append("# All sandbox tests (local + network):")
    lines.append("pytest tests/test_sandbox.py -v -m sandbox --runxfail")
    lines.append("")
    lines.append("# Local only (no network):")
    lines.append('pytest tests/test_sandbox.py -v -m "sandbox and not network"')
    lines.append("")
    lines.append("# With JUnit XML:")
    lines.append(
        "pytest tests/test_sandbox.py -m sandbox --runxfail --junitxml=report-sandbox.xml"
    )
    lines.append("```")
    lines.append("")

    try:
        report_path.write_text("\n".join(lines), encoding="utf-8")
        session.config.pluginmanager.get_plugin("terminalreporter").write_line(
            f"\n📄 Sandbox markdown report: {report_path}"
        )
    except OSError as exc:
        session.config.pluginmanager.get_plugin("terminalreporter").write_line(
            f"\n⚠️  Could not write sandbox report: {exc}"
        )


def pytest_sessionstart(session):
    """Record session start time for the markdown report."""
    global _SESSION_START
    _SESSION_START = time.monotonic()


# ── CLI flags ─────────────────────────────────────────────────────────────


def pytest_addoption(parser):
    parser.addoption(
        "--real-llm",
        action="store_true",
        default=False,
        help="Run E2E tests with a real LLM provider instead of mocks. "
        "Set PDF2TEX_TEST_PROVIDER and PDF2TEX_TEST_MODEL env vars "
        "(plus PDF2TEX_TEST_API_KEY / PDF2TEX_TEST_API_BASE if needed).",
    )


# ── Real-LLM config fixture ───────────────────────────────────────────────


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _migrate_test_db():
    """Ensure the test database is fully migrated before any test runs."""
    from app.db.database import init_db

    await init_db()


@pytest.fixture
def real_llm_config() -> dict:
    """LLM config for real-provider E2E tests, read from environment.

    Set these env vars before running ``pytest --real-llm``:

    * ``PDF2TEX_TEST_PROVIDER`` — provider id (e.g. "openai", "anthropic")
    * ``PDF2TEX_TEST_MODEL`` — model name (e.g. "gpt-4o-mini", "claude-3-5-sonnet")
    * ``PDF2TEX_TEST_API_KEY`` — API key (optional; falls back to provider env var)
    * ``PDF2TEX_TEST_API_BASE`` — custom API base URL (optional)

    Defaults to openai / gpt-4o-mini when env vars are not set.
    """
    provider = os.environ.get("PDF2TEX_TEST_PROVIDER", "openai")
    model = os.environ.get("PDF2TEX_TEST_MODEL", "gpt-4o-mini")
    api_key = os.environ.get("PDF2TEX_TEST_API_KEY", "")
    base_url = os.environ.get("PDF2TEX_TEST_API_BASE", "")
    config: dict = {"provider": provider, "model": model}
    if api_key:
        config["api_key"] = api_key
    if base_url:
        config["base_url"] = base_url
    return config


@pytest.fixture
def use_real_llm(request) -> bool:
    """True when ``--real-llm`` was passed on the command line."""
    return bool(request.config.getoption("--real-llm", default=False))


@pytest.fixture
def wikipedia_adapter():
    """Real Wikipedia adapter for E2E tests, language from env var.

    Set ``PDF2TEX_TEST_WIKI_LANG`` to override the default ("en").
    """
    from app.services.web_search import get_search_adapter

    lang = os.environ.get("PDF2TEX_TEST_WIKI_LANG", "en")
    config: dict[str, object] = {
        "tool_type": "wikipedia",
        "language": lang,
    }
    return get_search_adapter(config)


@pytest.fixture
def tavily_adapter():
    """Real Tavily adapter for E2E tests, skipped when key is not set.

    Set ``PDF2TEX_TEST_TAVILY_KEY`` in the environment before running.
    The test is automatically skipped when the env var is missing.
    """
    from app.services.web_search import get_search_adapter

    key = os.environ.get("PDF2TEX_TEST_TAVILY_KEY", "")
    if not key:
        pytest.skip("PDF2TEX_TEST_TAVILY_KEY not set")
    config: dict[str, object] = {
        "tool_type": "tavily",
        "api_key": key,
    }
    return get_search_adapter(config)


@pytest.fixture
def perplexity_adapter():
    """Real Perplexity adapter for E2E tests, skipped when key is not set.

    Set ``PDF2TEX_TEST_PERPLEXITY_KEY`` in the environment before running.
    The test is automatically skipped when the env var is missing.
    """
    from app.services.web_search import get_search_adapter

    key = os.environ.get("PDF2TEX_TEST_PERPLEXITY_KEY", "")
    if not key:
        pytest.skip("PDF2TEX_TEST_PERPLEXITY_KEY not set")
    config: dict[str, object] = {
        "tool_type": "perplexity",
        "api_key": key,
    }
    return get_search_adapter(config)


@pytest.fixture
def resolved_web_tools() -> list[dict[str, object]]:
    """Full resolved web tool configs for Web Agent ``_resolved_web_tools``.

    Includes Wikipedia (always, no API key needed) plus Tavily and/or
    Perplexity if their respective keys are set in the environment.
    """
    tools: list[dict[str, object]] = [
        {"tool_type": "wikipedia", "api_key": ""},
    ]
    tavily_key = os.environ.get("PDF2TEX_TEST_TAVILY_KEY", "")
    if tavily_key:
        tools.append({"tool_type": "tavily", "api_key": tavily_key})
    perplexity_key = os.environ.get("PDF2TEX_TEST_PERPLEXITY_KEY", "")
    if perplexity_key:
        tools.append({"tool_type": "perplexity", "api_key": perplexity_key})
    return tools


# ── Plan helpers ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_plan_same_chapter() -> list[PlannedSection]:
    """Two sections in the same chapter (for context-sharing tests)."""
    return [
        {
            "part_title": "Capitolo 1 - Fondamenti",
            "title": "1.1 Introduzione al Machine Learning",
            "order_index": 0,
            "outline": {
                "punti": [
                    "Definizione di machine learning",
                    "Paradigmi di apprendimento",
                    "Differenze con la programmazione tradizionale",
                ],
                "formule": [],
                "figure": [],
            },
            "source_filenames": ["appunti.pdf"],
        },
        {
            "part_title": "Capitolo 1 - Fondamenti",
            "title": "1.2 Apprendimento Supervisionato",
            "order_index": 1,
            "outline": {
                "punti": [
                    "Dataset etichettati",
                    "Regressione e classificazione",
                    "Metriche di valutazione",
                ],
                "formule": ["MSE = (1/n) * sum((y - y_hat)^2)"],
                "figure": [],
            },
            "source_filenames": ["appunti.pdf"],
        },
    ]


@pytest.fixture
def plan_two_chapters() -> list[PlannedSection]:
    """Sections in two different chapters (for parallel-chapter tests)."""
    return [
        {
            "part_title": "Capitolo 1 - Fondamenti",
            "title": "1.1 Introduzione",
            "order_index": 0,
            "outline": {"punti": ["Definizioni base"]},
            "source_filenames": ["appunti.pdf"],
        },
        {
            "part_title": "Capitolo 2 - Avanzato",
            "title": "2.1 Tecniche avanzate",
            "order_index": 1,
            "outline": {"punti": ["Deep learning", "Reti neurali"]},
            "source_filenames": ["appunti.pdf"],
        },
        {
            "part_title": "Capitolo 2 - Avanzato",
            "title": "2.2 Applicazioni",
            "order_index": 2,
            "outline": {"punti": ["Applicazioni pratiche"]},
            "source_filenames": ["appunti.pdf"],
        },
    ]


# ── Mock LLM responses ────────────────────────────────────────────────────


@pytest.fixture
def section1_latex() -> str:
    return (
        r"\section{Introduzione al Machine Learning}"
        r"\nIl machine learning è un ramo dell'intelligenza artificiale "
        r"che si occupa di creare sistemi che apprendono dai dati. "
        r"A differenza della programmazione tradizionale, dove le regole "
        r"sono esplicitate dal programmatore, nel ML il sistema inferisce "
        r"pattern dai dati. I tre paradigmi principali sono: supervisionato, "
        r"non supervisionato e apprendimento per rinforzo."
    )


@pytest.fixture
def section1_context_json() -> str:
    return json.dumps(
        [
            "Il machine learning crea sistemi che apprendono pattern dai dati",
            "Differisce dalla programmazione tradizionale perché le regole non sono esplicitate",
            "I tre paradigmi principali sono supervisionato, non supervisionato e per rinforzo",
        ]
    )


@pytest.fixture
def section2_latex() -> str:
    return (
        r"\section{Apprendimento Supervisionato}"
        r"\nCome introdotto precedentemente, l'apprendimento supervisionato "
        r"utilizza dataset con etichette note. I due task principali sono "
        r"la regressione (predizione di valori continui) e la classificazione "
        r"(assegnazione a categorie discrete). Le metriche di valutazione "
        r"includono MSE, RMSE per la regressione e accuratezza, precisione, "
        r"recall per la classificazione."
    )


@pytest.fixture
def section2_context_json() -> str:
    return json.dumps(
        [
            "L'apprendimento supervisionato usa dataset con etichette note",
            "I task principali sono regressione e classificazione",
            "Le metriche includono MSE per regressione e accuratezza per classificazione",
        ]
    )


@pytest.fixture
def documents() -> dict[str, str]:
    """Small source text for writer tests."""
    return {"appunti.pdf": "Testo di esempio sul machine learning." * 20}


@pytest.fixture
def documents_no_apprendono() -> dict[str, str]:
    """Source text that deliberately excludes the word 'apprendono'."""
    return {
        "appunti.pdf": (
            "Il machine learning è un campo dell'AI. "
            "I paradigmi sono supervisionato, non supervisionato e rinforzo. "
            "Il supervisionato usa dati etichettati per regressione e classificazione. "
            "MSE misura l'errore quadratico medio. "
        )
        * 10
    }


@pytest.fixture
def fake_llm_config() -> dict:
    return {"provider": "fake", "model": "test"}


# ── DB-backed test fixtures ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def fake_provider_and_project():
    """Create UUID-suffixed ProviderConfig + Project in the test DB.

    Yields ``(provider_id, project_id)``.  Records are automatically deleted
    after the test completes (teardown is defensive — skips if already removed).

    The project has ``status=uploaded`` and total_sources=0.  Use your own
    ``async_session()`` block to add Sources or tweak project fields.
    """
    import uuid

    from app.db.database import async_session
    from app.db.models import Project, ProjectStatus, ProviderConfig

    uid = uuid.uuid4().hex[:8]

    async with async_session() as session:
        provider = ProviderConfig(
            name=f"test-fixture-{uid}",
            provider_type="fake",
            default_model="fake-echo",
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        project = Project(
            name=f"Test Fixture-{uid}",
            language="english",
            status=ProjectStatus.uploaded,
        )
        session.add(project)
        await session.flush()
        await session.commit()

        _provider_id = provider.id
        _project_id = project.id

    yield _provider_id, _project_id

    # ── Teardown: delete records (defensive, returns early if absent) ──────
    async with async_session() as session:
        p = await session.get(Project, _project_id)
        if p is not None:
            await session.delete(p)
        pr = await session.get(ProviderConfig, _provider_id)
        if pr is not None:
            await session.delete(pr)
        await session.commit()
