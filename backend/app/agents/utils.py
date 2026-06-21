"""Helpers shared across agents.

Centralises every LLM interaction so robustness lives in one place:

* a per-config cache of chat models (avoids re-instantiating a client for every
  one of the dozens of analyze/write calls);
* automatic retry with exponential backoff + jitter on transient errors
  (rate limits, timeouts, 5xx);
* a concurrency gate (semaphore) so fan-out cannot overwhelm a provider;
* a global RPM (requests per minute) sliding-window gate that pauses callers
  when the per-minute budget is exhausted (configurable, default 30 rpm);
* structured-output helpers that validate against Pydantic schemas, with a
  lenient JSON fallback for providers that cannot honour a schema;
* lightweight token/cost accounting for logging and debugging.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.config import settings
from app.core.llm_factory import LLMConfig, create_llm
from app.core.logging import get_logger

logger = get_logger("llm")

T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------- #
# RPM (requests-per-minute) gate — sliding-window scheduler                    #
# --------------------------------------------------------------------------- #
class _RPMLimiter:
    """A sliding-window global RPM gate.

    Before every LLM call the scheduler checks whether the per-minute budget has
    been exhausted in the preceding 60-second window.  When it has, the caller
    sleeps until the oldest recorded request ages out of the window.  Calls that
    are already in-progress are NOT counted — only dispatch timestamps matter.

    The limiter is active when ``settings.llm_rpm_enabled`` is True AND the
    effective ``rpm_limit`` (global default or per-call override) is positive.
    """

    def __init__(self) -> None:
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self, label: str = "llm", rpm_limit: int | None = None) -> None:
        """Block until a request slot is available in the RPM window.

        When ``rpm_limit`` is provided it overrides the global default; when it
        is 0 or negative (or the global ``llm_rpm_enabled`` is False) this is a
        no-op.
        """
        effective_rpm = rpm_limit
        if effective_rpm is None:
            effective_rpm = settings.llm_rpm_limit if settings.llm_rpm_enabled else 0
        if not settings.llm_rpm_enabled or effective_rpm <= 0:
            return

        # Check the window and compute how long we need to wait (if at all)
        # WITHOUT holding the lock during the sleep, so other coroutines can
        # observe the state while one is waiting.
        wait_for = 0.0
        budget_count = 0
        async with self._lock:
            now = time.monotonic()
            window_start = now - 60.0
            self._timestamps = [t for t in self._timestamps if t > window_start]
            budget_count = len(self._timestamps)
            if budget_count >= effective_rpm:
                oldest = self._timestamps[0]
                wait_for = max(0.0, oldest - window_start)

        if wait_for > 0:
            logger.info(
                "RPM gate: %d/%d richieste in finestra, pausa %.1fs per '%s'",
                budget_count,
                effective_rpm,
                wait_for,
                label,
            )
            await asyncio.sleep(wait_for)
            # Re-acquire the lock after sleep and re-check the window.
            # Another coroutine may have added a timestamp while we slept.
            async with self._lock:
                now = time.monotonic()
                window_start = now - 60.0
                self._timestamps = [t for t in self._timestamps if t > window_start]
                while len(self._timestamps) >= effective_rpm:
                    oldest = self._timestamps[0]
                    extra_wait = max(0.0, oldest - window_start)
                    if extra_wait <= 0:
                        break
                    # Release the lock before sleeping; re-check after.
                    self._lock.release()
                    try:
                        await asyncio.sleep(extra_wait)
                    finally:
                        await self._lock.acquire()
                    now = time.monotonic()
                    window_start = now - 60.0
                    self._timestamps = [t for t in self._timestamps if t > window_start]
                self._timestamps.append(now)
            return

        async with self._lock:
            self._timestamps.append(now)


_RPM_LIMITER: _RPMLimiter | None = None


def _get_rpm_limiter() -> _RPMLimiter:
    global _RPM_LIMITER
    if _RPM_LIMITER is None:
        _RPM_LIMITER = _RPMLimiter()
    return _RPM_LIMITER


async def acquire_rpm_slot(label: str = "llm", rpm_limit: int | None = None) -> None:
    """Public hook: wait until the global RPM gate allows one more request.

    This is the stable cross-module API.  Call it before every LLM invocation.
    When ``llm_rpm_enabled`` is False or the effective limit is ≤ 0, it returns
    immediately.
    """
    await _get_rpm_limiter().acquire(label, rpm_limit)


# Global gate so the total number of concurrent LLM calls stays bounded even
# across multiple fan-out stages.
# Lazily initialised per running event loop so that pytest-asyncio (which
# creates a fresh event loop per test) doesn't trip over a bound-in-wrong-loop
# RuntimeError.  In production the loop never changes, so the semaphore is
# created exactly once.
_SEMAPHORE_STATE: dict[str, Any] = {"loop": None, "sem": None}


def _get_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if _SEMAPHORE_STATE["loop"] is not loop:
        _SEMAPHORE_STATE["loop"] = loop
        _SEMAPHORE_STATE["sem"] = asyncio.Semaphore(
            max(1, settings.llm_max_concurrency)
        )
    return _SEMAPHORE_STATE["sem"]


# Cache of instantiated chat models, keyed by a hashable view of the config.
_MODEL_CACHE: dict[tuple, Any] = {}
_CACHE_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Token accounting                                                              #
# --------------------------------------------------------------------------- #
class _TokenCounter:
    """Process-wide running total of token usage (best-effort)."""

    def __init__(self) -> None:
        self.input = 0
        self.output = 0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, in_tok: int, out_tok: int) -> None:
        with self._lock:
            self.input += in_tok
            self.output += out_tok
            self.calls += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "calls": self.calls,
                "input_tokens": self.input,
                "output_tokens": self.output,
                "total_tokens": self.input + self.output,
            }


tokens = _TokenCounter()


def _config_key(cfg: LLMConfig, temperature: float | None) -> tuple:
    extra = tuple(sorted((cfg.extra_params or {}).items()))
    return (
        cfg.provider,
        cfg.model,
        cfg.api_key,
        cfg.base_url,
        cfg.temperature if temperature is None else temperature,
        cfg.max_tokens,
        cfg.top_p,
        extra,
    )


def _get_model(cfg: LLMConfig, temperature: float | None) -> Any:
    """Return a cached chat model for this config/temperature combination."""
    key = _config_key(cfg, temperature)
    with _CACHE_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            build_cfg = cfg
            if temperature is not None and temperature != cfg.temperature:
                build_cfg = LLMConfig(**{**asdict(cfg), "temperature": temperature})
            model = create_llm(build_cfg)
            _MODEL_CACHE[key] = model
    return model


def _record_usage(result: Any) -> None:
    meta = getattr(result, "usage_metadata", None)
    if isinstance(meta, dict):
        tokens.add(int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0)))


_TRANSIENT_HINTS = (
    "rate limit",
    "ratelimit",
    "429",
    "timeout",
    "timed out",
    "overloaded",
    "503",
    "502",
    "500",
    "temporarily",
    "connection",
    "reset",
)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in _TRANSIENT_HINTS)


async def _ainvoke_with_retry(
    model: Any,
    messages: list,
    label: str,
    rpm_limit: int | None = None,
    fallback_model: Any = None,
    fallback_rpm_limit: int | None = None,
) -> Any:
    """Invoke a model with bounded retries + exponential backoff and jitter.

    Each call is bounded by ``llm_request_timeout`` so a hung provider cannot
    stall the whole run: a timeout is treated as a transient error and retried.

    When ``fallback_model`` is provided and primary retries are exhausted on a
    *transient* error, the call is retried on the fallback model with a fresh
    set of retries before giving up entirely.
    """
    attempts = max(1, settings.llm_max_retries)
    timeout = settings.llm_request_timeout if settings.llm_request_timeout > 0 else None

    async def _invoke_one(m: Any, rpm: int | None = rpm_limit) -> Any:
        async with _get_semaphore():
            await _get_rpm_limiter().acquire(label, rpm)
            if timeout is None:
                return await m.ainvoke(messages)
            return await asyncio.wait_for(m.ainvoke(messages), timeout=timeout)

    last_exc: Exception | None = None
    # ── Primary model ──────────────────────────────────────────────────────
    for attempt in range(1, attempts + 1):
        try:
            return await _invoke_one(model)
        except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
            last_exc = exc
            timed_out = isinstance(exc, asyncio.TimeoutError)
            transient = timed_out or _is_transient(exc)
            if timed_out:
                last_exc = TimeoutError(f"richiesta LLM oltre il timeout di {timeout}s")
            if attempt >= attempts or not transient:
                if not transient or fallback_model is None:
                    logger.error(
                        "LLM '%s' fallito al tentativo %d/%d: %s",
                        label,
                        attempt,
                        attempts,
                        exc,
                    )
                    raise
                # Switch to fallback below.
                break
            delay = settings.llm_retry_base_delay * (2 ** (attempt - 1))
            delay += random.uniform(0, delay * 0.25)  # jitter
            logger.warning(
                "LLM '%s' errore transitorio (tentativo %d/%d), retry tra %.1fs: %s",
                label,
                attempt,
                attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)

    # ── Fallback model ─────────────────────────────────────────────────────
    if fallback_model is None:
        assert last_exc is not None
        raise last_exc

    logger.warning("LLM '%s': provider primario esaurito, passaggio al fallback", label)
    for attempt in range(1, attempts + 1):
        try:
            return await _invoke_one(fallback_model, fallback_rpm_limit)
        except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
            last_exc = exc
            timed_out = isinstance(exc, asyncio.TimeoutError)
            transient = timed_out or _is_transient(exc)
            if attempt >= attempts or not transient:
                logger.error(
                    "LLM '%s' fallback fallito al tentativo %d/%d: %s",
                    label,
                    attempt,
                    attempts,
                    exc,
                )
                raise
            delay = settings.llm_retry_base_delay * (2 ** (attempt - 1))
            delay += random.uniform(0, delay * 0.25)
            logger.warning(
                "LLM '%s' fallback errore (tentativo %d/%d), retry tra %.1fs: %s",
                label,
                attempt,
                attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _build_fallback_model(
    llm_config: dict[str, Any], temperature: float | None
) -> tuple[Any, int | None]:
    """Build a fallback model and its RPM limit from ``fallback_llm_config``.

    Returns ``(model, rpm_limit)`` — both are ``None`` when no fallback is
    configured.
    """
    fallback_cfg_dict = llm_config.get("fallback_llm_config")
    if not fallback_cfg_dict:
        return None, None
    fallback_cfg = LLMConfig(**fallback_cfg_dict)
    return _get_model(fallback_cfg, temperature), fallback_cfg_dict.get("rpm_limit")


async def call_llm(
    llm_config: dict[str, Any],
    system: str,
    user: str,
    temperature: float | None = None,
    label: str = "llm",
) -> str:
    """Invoke the configured LLM with a system + user message, return text."""
    cfg = LLMConfig(**llm_config)
    model = _get_model(cfg, temperature)
    fallback_model, fallback_rpm = _build_fallback_model(llm_config, temperature)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    result = await _ainvoke_with_retry(
        model,
        messages,
        label,
        rpm_limit=llm_config.get("rpm_limit"),
        fallback_model=fallback_model,
        fallback_rpm_limit=fallback_rpm,
    )
    _record_usage(result)
    return str(getattr(result, "content", result))


async def call_llm_structured(
    llm_config: dict[str, Any],
    system: str,
    user: str,
    schema: type[T],
    temperature: float | None = None,
    label: str = "llm",
) -> T:
    """Return a validated ``schema`` instance from the LLM.

    Tries native structured output (function calling / JSON mode) when the
    provider supports it; otherwise falls back to a plain call plus robust JSON
    extraction. Always returns a valid (possibly default) schema instance, so
    callers never crash on malformed output.
    """
    cfg = LLMConfig(**llm_config)
    model = _get_model(cfg, temperature)
    fallback_model, fallback_rpm = _build_fallback_model(llm_config, temperature)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    # Native structured output (skip for the offline fake model).
    if cfg.provider != "fake":
        try:
            structured = model.with_structured_output(schema)
            result = await _ainvoke_with_retry(
                structured,
                messages,
                label,
                rpm_limit=llm_config.get("rpm_limit"),
                fallback_model=fallback_model,
                fallback_rpm_limit=fallback_rpm,
            )
            if isinstance(result, schema):
                return result
            if isinstance(result, dict):
                return schema.model_validate(result)
        except Exception as exc:  # noqa: BLE001 - fall back to manual parsing
            logger.debug("structured output non supportato per '%s': %s", label, exc)

    raw = await call_llm(llm_config, system, user, temperature=temperature, label=label)
    data = parse_json_response(raw)
    if isinstance(data, dict):
        try:
            return schema.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - return defaults on bad shape
            logger.warning("Output JSON non conforme allo schema '%s': %s", label, exc)
    else:
        logger.warning("Nessun JSON valido nella risposta di '%s'", label)
    return schema()


def _image_to_data_uri(path: Path) -> str | None:
    """Read an image file and return a base64 ``data:`` URI (or None on error)."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        logger.debug("Immagine non leggibile %s: %s", path, exc)
        return None
    ext = path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    return f"data:image/{mime};base64," + base64.b64encode(raw).decode("ascii")


async def call_vision_structured(
    llm_config: dict[str, Any],
    system: str,
    user: str,
    images: list[Path],
    schema: type[T],
    temperature: float | None = None,
    label: str = "vision",
) -> T | None:
    """Validated ``schema`` from a multimodal (text + images) LLM call.

    Sends the page images alongside the text prompt so a vision-capable model
    can judge the document the way a person would. Returns ``None`` when vision
    is unavailable for this provider/model (the caller then falls back to a
    text-only review). The offline ``fake`` provider has no vision, so it also
    returns ``None``.
    """
    cfg = LLMConfig(**llm_config)
    if cfg.provider == "fake" or not images:
        return None

    content: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for img in images:
        uri = _image_to_data_uri(img)
        if uri:
            content.append({"type": "image_url", "image_url": {"url": uri}})
    if len(content) == 1:  # no images survived
        return None

    model = _get_model(cfg, temperature)
    fallback_model, fallback_rpm = _build_fallback_model(llm_config, temperature)
    messages = [SystemMessage(content=system), HumanMessage(content=content)]
    try:
        structured = model.with_structured_output(schema)
        result = await _ainvoke_with_retry(
            structured,
            messages,
            label,
            rpm_limit=llm_config.get("rpm_limit"),
            fallback_model=fallback_model,
            fallback_rpm_limit=fallback_rpm,
        )
        if isinstance(result, schema):
            return result
        if isinstance(result, dict):
            return schema.model_validate(result)
    except Exception as exc:  # noqa: BLE001 - fall back to text-only judge
        logger.warning("Vision judge non disponibile per '%s': %s", label, exc)
        return None

    # Some providers return text even with structured output; parse leniently.
    try:
        raw_result = await _ainvoke_with_retry(
            model,
            messages,
            label,
            rpm_limit=llm_config.get("rpm_limit"),
            fallback_model=fallback_model,
            fallback_rpm_limit=fallback_rpm,
        )
        _record_usage(raw_result)
        data = parse_json_response(str(getattr(raw_result, "content", raw_result)))
        if isinstance(data, dict):
            return schema.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - give up on vision, use text fallback
        logger.warning("Vision judge fallback fallito per '%s': %s", label, exc)
    return None


def parse_json_response(text: str) -> Any:
    """Best-effort extraction of a JSON object/array from an LLM response."""
    text = text.strip()
    # Strip markdown code fences
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    # Find first { or [
    match = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last-ditch repair: trim trailing commas before } or ].
        repaired = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None


def strip_latex_fences(text: str) -> str:
    """Remove markdown code fences around LaTeX output."""
    text = text.strip()
    fenced = re.search(r"```(?:latex|tex)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text


def compile_error_excerpt(log: str, max_lines: int = 6) -> str:
    """Pull the most relevant error lines out of a pdflatex log for the UI."""
    if not log:
        return ""
    lines = [ln for ln in log.splitlines() if ln.strip()]
    errors = [
        ln for ln in lines if ln.startswith("!") or "Error" in ln or "Undefined" in ln
    ]
    chosen = errors[:max_lines] or lines[-max_lines:]
    return " | ".join(ln.strip()[:160] for ln in chosen)
