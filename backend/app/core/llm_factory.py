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
    """Try a tiny generation to validate provider credentials/connectivity."""
    try:
        llm = create_llm(config)
        result = await llm.ainvoke("Reply with the single word: ok")
        text = getattr(result, "content", str(result))
        return {"success": True, "response": str(text)[:200]}
    except Exception as exc:  # noqa: BLE001 - surface any provider error to the UI
        return {"success": False, "error": str(exc)}


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
