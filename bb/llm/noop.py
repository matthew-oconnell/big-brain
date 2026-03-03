"""No-op LLM client — skips context estimation. Fast, offline, zero cost."""

from bb.llm.base import ContextEstimate


class NoopLLM:
    async def estimate_context(self, content: str, content_type: str) -> ContextEstimate:
        return ContextEstimate(summary="", activity_tags=[])
