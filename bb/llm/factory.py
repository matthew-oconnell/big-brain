"""Instantiate the configured LLM client from settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bb.core.config import Settings
    from bb.llm.base import LLMClient


def get_llm_client(settings: "Settings") -> "LLMClient":
    provider = settings.llm.provider

    if provider == "anthropic":
        from bb.llm.anthropic_llm import AnthropicLLM
        return AnthropicLLM(model=settings.llm.model)

    if provider == "ollama":
        from bb.llm.ollama_llm import OllamaLLM
        return OllamaLLM(
            model=settings.llm.ollama_model,
            base_url=settings.llm.base_url or "http://localhost:11434",
        )

    from bb.llm.noop import NoopLLM
    return NoopLLM()
