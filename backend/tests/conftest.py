"""Shared fixtures and helpers for the test suite."""

import json
import os

import pytest
import pytest_asyncio

from app.agents.state import PlannedSection

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
    api_base = os.environ.get("PDF2TEX_TEST_API_BASE", "")
    config: dict = {"provider": provider, "model": model}
    if api_key:
        config["api_key"] = api_key
    if api_base:
        config["api_base"] = api_base
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
