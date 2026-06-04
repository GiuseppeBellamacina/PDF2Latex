"""Helpers shared across agents."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import LLMConfig, create_llm


async def call_llm(llm_config: dict[str, Any], system: str, user: str) -> str:
    """Invoke the configured LLM with a system + user message, return text."""
    llm = create_llm(LLMConfig(**llm_config))
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    result = await llm.ainvoke(messages)
    return str(getattr(result, "content", result))


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
        return None


def strip_latex_fences(text: str) -> str:
    """Remove markdown code fences around LaTeX output."""
    text = text.strip()
    fenced = re.search(r"```(?:latex|tex)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text
