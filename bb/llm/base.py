"""Protocol for LLM context estimation backends."""

from typing import Protocol

from pydantic import BaseModel


class ContextEstimate(BaseModel):
    summary: str  # one sentence: what was the user working on?
    activity_tags: list[str]  # 3-5 tags, e.g. ["cfd", "python", "debugging"]


class LLMClient(Protocol):
    async def estimate_context(self, content: str, content_type: str) -> ContextEstimate:
        """Given a chunk of content, estimate what the user was doing."""
        ...
