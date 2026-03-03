"""LLM context estimation via the Anthropic API (Claude)."""

from __future__ import annotations

import json
import logging
import os

import anthropic

from bb.llm.base import ContextEstimate

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """\
You are helping build a personal knowledge store. Given a snippet of content, \
estimate what the user was working on when this was created.

Content type: {content_type}
Content (first 600 chars):
{content}

Respond with JSON only — no markdown fences, no extra text:
{{"summary": "<one sentence describing what the user was working on>", "activity_tags": ["tag1", "tag2", "tag3"]}}
"""


class AnthropicLLM:
    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it or switch to provider = 'ollama' in your config."
            )
        self._client = anthropic.AsyncAnthropic()
        self._model = model

    async def estimate_context(self, content: str, content_type: str) -> ContextEstimate:
        prompt = PROMPT_TEMPLATE.format(
            content_type=content_type,
            content=content[:600],
        )
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown fences if the model added them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        return ContextEstimate(
            summary=data.get("summary", ""),
            activity_tags=data.get("activity_tags", []),
        )
