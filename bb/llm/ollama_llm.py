"""LLM context estimation via a local Ollama server."""

from __future__ import annotations

import json
import logging
import re

import httpx

from bb.llm.base import ContextEstimate

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """\
/no_think
You are helping build a personal knowledge store. Given a snippet of content, \
estimate what the user was working on when this was created.

Content type: {content_type}
Content (first 600 chars):
{content}

Respond with JSON only — no markdown fences, no extra text:
{{"summary": "<one sentence describing what the user was working on>", "activity_tags": ["tag1", "tag2", "tag3"]}}
"""

# Qwen3 and some other models emit <think>...</think> blocks — strip them
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _extract_json(raw: str) -> dict:
    """Strip thinking blocks and markdown fences, then parse JSON."""
    cleaned = _THINK_RE.sub("", raw).strip()
    # Strip ```json ... ``` if the model added them anyway
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned.strip())


class OllamaLLM:
    def __init__(
        self,
        model: str = "alibayram/Qwen3-30B-A3B-Instruct-2507:latest",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    async def estimate_context(self, content: str, content_type: str) -> ContextEstimate:
        prompt = PROMPT_TEMPLATE.format(
            content_type=content_type,
            content=content[:600],
        )
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",  # Ollama JSON mode — forces valid JSON output
                    "options": {
                        "temperature": 0.1,  # low temp for consistent structured output
                    },
                },
            )
            response.raise_for_status()
            raw = response.json()["response"]
            data = _extract_json(raw)
            return ContextEstimate(
                summary=data.get("summary", ""),
                activity_tags=data.get("activity_tags", []),
            )

    async def is_available(self) -> bool:
        """Check if the Ollama server is reachable and the model is loaded."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self._base_url}/api/tags")
                r.raise_for_status()
                models = [m["name"] for m in r.json().get("models", [])]
                return any(self._model in m or m in self._model for m in models)
        except Exception:
            return False
