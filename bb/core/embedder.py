"""Local embedding via fastembed — no external API calls."""

from __future__ import annotations

from functools import lru_cache

from fastembed import TextEmbedding

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"


@lru_cache(maxsize=1)
def _get_model() -> TextEmbedding:
    """Load model once and cache it for the process lifetime."""
    return TextEmbedding(model_name=MODEL_NAME)


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns list of 768-dim float vectors."""
    model = _get_model()
    return [v.tolist() for v in model.embed(texts)]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
