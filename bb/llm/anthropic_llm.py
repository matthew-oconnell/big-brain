"""LLM context estimation via the Anthropic API (Claude)."""

import anthropic

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


class AnthropicLLM:
    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self._client = anthropic.AsyncAnthropic()
        self._model = model

    async def estimate_context(self, content: str, content_type: str) -> ContextEstimate:
        import json

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
        data = json.loads(raw)
        return ContextEstimate(**data)
