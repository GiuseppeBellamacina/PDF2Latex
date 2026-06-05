"""Helpers shared across agents.

Centralises every LLM interaction so robustness lives in one place:

* a per-config cache of chat models (avoids re-instantiating a client for every
  one of the dozens of analyze/write calls);
* automatic retry with exponential backoff + jitter on transient errors
  (rate limits, timeouts, 5xx);
* a concurrency gate (semaphore) so fan-out cannot overwhelm a provider;
* structured-output helpers that validate against Pydantic schemas, with a
  lenient JSON fallback for providers that cannot honour a schema;
* lightweight token/cost accounting for logging and debugging.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import threading
from dataclasses import asdict
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.config import settings
from app.core.llm_factory import LLMConfig, create_llm
from app.core.logging import get_logger

logger = get_logger("llm")

T = TypeVar("T", bound=BaseModel)

# Global gate so the total number of concurrent LLM calls stays bounded even
# across multiple fan-out stages.
_SEMAPHORE = asyncio.Semaphore(max(1, settings.llm_max_concurrency))

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


async def _ainvoke_with_retry(model: Any, messages: list, label: str) -> Any:
    """Invoke a model with bounded retries + exponential backoff and jitter."""
    attempts = max(1, settings.llm_max_retries)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with _SEMAPHORE:
                return await model.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001 - decide retry vs. propagate
            last_exc = exc
            transient = _is_transient(exc)
            if attempt >= attempts or not transient:
                logger.error(
                    "LLM '%s' fallito al tentativo %d/%d: %s",
                    label,
                    attempt,
                    attempts,
                    exc,
                )
                raise
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
    assert last_exc is not None
    raise last_exc


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
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    result = await _ainvoke_with_retry(model, messages, label)
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
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    # Native structured output (skip for the offline fake model).
    if cfg.provider != "fake":
        try:
            structured = model.with_structured_output(schema)
            result = await _ainvoke_with_retry(structured, messages, label)
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
