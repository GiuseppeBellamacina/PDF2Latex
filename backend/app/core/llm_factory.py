"""LLM factory: build a LangChain chat model from a provider configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel


@dataclass
class LLMConfig:
    """Configuration for an LLM provider instance."""

    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None
    top_p: float | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider = self.provider.lower()


def create_llm(config: LLMConfig) -> BaseChatModel:
    """Create a LangChain chat model from a config object."""

    params: dict[str, Any] = {"model": config.model, "temperature": config.temperature}
    if config.max_tokens is not None:
        params["max_tokens"] = config.max_tokens
    if config.top_p is not None:
        params["top_p"] = config.top_p

    match config.provider:
        case "fake":
            return FakeChatModel(model_name=config.model or "fake-echo")

        case "openai" | "custom":
            from langchain_openai import ChatOpenAI

            if config.api_key:
                params["api_key"] = config.api_key
            if config.base_url:
                params["base_url"] = config.base_url
            params.update(config.extra_params)
            return ChatOpenAI(**params)

        case "anthropic":
            from langchain_anthropic import ChatAnthropic

            if config.api_key:
                params["api_key"] = config.api_key
            if config.base_url:
                params["base_url"] = config.base_url
            params.update(config.extra_params)
            return ChatAnthropic(**params)

        case "ollama":
            from langchain_ollama import ChatOllama

            if config.base_url:
                params["base_url"] = config.base_url
            params.update(config.extra_params)
            return ChatOllama(**params)

        case _:
            raise ValueError(f"Unknown provider: {config.provider}")


async def test_llm_connection(config: LLMConfig) -> dict[str, Any]:
    """Run a small real generation to validate a provider and report details.

    Returns a rich result: whether the round-trip worked, how long it took, the
    model that actually answered, the reply text, a sanity check that the model
    followed a tiny instruction, and token usage when the provider reports it.
    """
    import time

    prompt = (
        "You are validating an API connection. "
        "Reply with exactly this phrase and nothing else: PDF2LATEX_OK"
    )
    try:
        llm = create_llm(config)
    except Exception as exc:  # noqa: BLE001 - configuration/build error
        return {
            "success": False,
            "stage": "setup",
            "error": str(exc),
        }

    start = time.perf_counter()
    try:
        result = await llm.ainvoke(prompt)
    except Exception as exc:  # noqa: BLE001 - surface any provider error to the UI
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "success": False,
            "stage": "request",
            "error": str(exc),
            "error_type": type(exc).__name__,
            "latency_ms": latency_ms,
        }

    latency_ms = int((time.perf_counter() - start) * 1000)
    text = str(getattr(result, "content", result)).strip()

    # Did the model follow the instruction? (informational, not a hard failure)
    followed = "PDF2LATEX_OK" in text.upper()

    # Best-effort model + token usage extraction across providers.
    meta = getattr(result, "response_metadata", {}) or {}
    usage = getattr(result, "usage_metadata", None) or {}
    model_name = (
        meta.get("model_name")
        or meta.get("model")
        or getattr(result, "model", None)
        or config.model
    )
    tokens: dict[str, int] | None = None
    if usage:
        tokens = {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
            "total": usage.get("total_tokens", 0),
        }

    return {
        "success": True,
        "latency_ms": latency_ms,
        "model": model_name,
        "followed_instruction": followed,
        "response": text[:300],
        "tokens": tokens,
    }


# --------------------------------------------------------------------------- #
# Offline fake model: lets you exercise the full pipeline without any API key. #
# --------------------------------------------------------------------------- #
class FakeChatModel(BaseChatModel):
    """A trivial offline chat model that echoes a deterministic placeholder."""

    model_name: str = "fake-echo"

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        prompt = messages[-1].content if messages else ""
        text = (
            "% [fake-llm] contenuto segnaposto generato offline\n"
            "\\section{Sezione di esempio}\n"
            "Questo testo \\`e prodotto dal modello \\emph{fake} per testare la pipeline "
            "senza chiamate a un provider reale.\n\n"
            f"% prompt length: {len(str(prompt))} caratteri\n"
        )
        message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
