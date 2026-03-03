"""LLM context estimation via a local Ollama server."""

import json

import httpx

from bb.llm.base import ContextEstimate

PROMPT_TEMPLATE = """\
You are helping build a personal knowledge store. Given a snippet of content, \
estimate what the user was working on when this was created.

Content type: {content_type}
Content (first 600 chars):
{content}

Respond with JSON only, no markdown:
{{"summary": "<one sentence>", "activity_tags": ["tag1", "tag2", "tag3"]}}
"""


class OllamaLLM:
    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self._model = model
        self._base_url = base_url

    async def estimate_context(self, content: str, content_type: str) -> ContextEstimate:
        prompt = PROMPT_TEMPLATE.format(
            content_type=content_type,
            content=content[:600],
        )
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            raw = response.json()["response"].strip()
            data = json.loads(raw)
            return ContextEstimate(**data)
