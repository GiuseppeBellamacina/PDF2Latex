"""Unit tests for the _RPMLimiter sliding-window RPM gate."""

from __future__ import annotations

import time

import pytest

from app.agents.utils import _RPMLimiter
from app.core.config import settings


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_rpm_limiter_disabled(monkeypatch):
    """No sleep when llm_rpm_enabled is False — returns immediately.

    Passing rpm_limit=5 here proves the global kill-switch takes priority
    over per-call overrides: when the gate is off, even explicit limits
    are ignored.
    """
    monkeypatch.setattr(settings, "llm_rpm_enabled", False)
    limiter = _RPMLimiter()

    start = time.monotonic()
    await limiter.acquire("test", rpm_limit=5)
    elapsed = time.monotonic() - start

    assert elapsed < 0.1, "Should return immediately when globally disabled"
    assert len(limiter._timestamps) == 0, "No timestamp recorded"


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_rpm_limiter_zero_limit(monkeypatch):
    """No sleep when per-call rpm_limit is 0 — returns immediately."""
    monkeypatch.setattr(settings, "llm_rpm_enabled", True)
    limiter = _RPMLimiter()

    start = time.monotonic()
    await limiter.acquire("test", rpm_limit=0)
    elapsed = time.monotonic() - start

    assert elapsed < 0.1, "Should return immediately when limit is 0"
    assert len(limiter._timestamps) == 0


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_rpm_limiter_under_budget(monkeypatch):
    """Multiple acquires without sleeping when under the RPM budget."""
    monkeypatch.setattr(settings, "llm_rpm_enabled", True)
    limiter = _RPMLimiter()

    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire("test", rpm_limit=10)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5, f"Under budget: expected near-instant, got {elapsed:.2f}s"
    assert len(limiter._timestamps) == 5, "All 5 timestamps recorded"


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_rpm_limiter_sleeps_when_exhausted(monkeypatch):
    """Sleeps when the RPM budget is full until a slot ages out of the window."""
    monkeypatch.setattr(settings, "llm_rpm_enabled", True)
    limiter = _RPMLimiter()

    # Pre-fill with timestamps 59 s ago — they expire in ~1 second.
    now = time.monotonic()
    limiter._timestamps = [now - 59.0] * 5

    start = time.monotonic()
    await limiter.acquire("test", rpm_limit=5)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.3, (
        f"Expected to sleep when budget exhausted, but only {elapsed:.2f}s elapsed"
    )
    # After the sleep, old entries are purged; only the new one remains.
    assert len(limiter._timestamps) == 1, (
        f"Expected 1 timestamp after purge, got {len(limiter._timestamps)}"
    )


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_rpm_limiter_uses_global_default(monkeypatch):
    """Uses settings.llm_rpm_limit when no per-call rpm_limit is given."""
    monkeypatch.setattr(settings, "llm_rpm_enabled", True)
    monkeypatch.setattr(settings, "llm_rpm_limit", 100)  # generous global default
    limiter = _RPMLimiter()

    start = time.monotonic()
    for _ in range(10):
        await limiter.acquire("test")  # no explicit rpm_limit → global 100
    elapsed = time.monotonic() - start

    assert elapsed < 0.5, (
        f"Global default of 100 RPM: 10 calls should not sleep, got {elapsed:.2f}s"
    )
    assert len(limiter._timestamps) == 10


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_rpm_limiter_per_call_override_takes_priority(monkeypatch):
    """Per-call rpm_limit overrides the global default."""
    monkeypatch.setattr(settings, "llm_rpm_enabled", True)
    monkeypatch.setattr(settings, "llm_rpm_limit", 100)  # generous global
    limiter = _RPMLimiter()

    # Fill budget for limit=3.
    now = time.monotonic()
    limiter._timestamps = [now - 59.0] * 3

    start = time.monotonic()
    await limiter.acquire("test", rpm_limit=3)  # per-call override
    elapsed = time.monotonic() - start

    assert elapsed >= 0.3, (
        f"Per-call limit=3 should trigger sleep when budget full, "
        f"but only {elapsed:.2f}s elapsed"
    )
