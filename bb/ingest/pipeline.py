"""
Ingest pipeline — the single path all content takes into the brain.

Flow:
  1. Receive a Chunk (content + metadata)
  2. Deduplicate (skip if hash already seen)
  3. Split into sub-chunks if needed
  4. Embed each chunk
  5. Save to vector store + metadata store + blob store
  6. Queue async LLM context estimation
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from bb.core.chunk import Chunk, ContentType
from bb.core.config import Settings
from bb.core.embedder import embed
from bb.ingest.chunker import chunk_text
from bb.llm.base import LLMClient
from bb.llm.noop import NoopLLM
from bb.storage.blob.local import LocalBlobStore
from bb.storage.meta import MetaStore
from bb.storage.vector import VectorStore

logger = logging.getLogger(__name__)


class IngestPipeline:
    def __init__(
        self,
        settings: Settings,
        llm: LLMClient | None = None,
    ) -> None:
        settings.ensure_dirs()
        self._settings = settings
        self._llm = llm or NoopLLM()
        self._vector = VectorStore(settings.storage.data_dir)
        self._meta = MetaStore(settings.storage.data_dir)
        self._blobs = LocalBlobStore(settings.storage.data_dir / "blobs")
        self._context_queue: asyncio.Queue[str] = asyncio.Queue()

    async def ingest(self, chunk: Chunk) -> list[str]:
        """
        Ingest a single Chunk. Returns list of stored chunk IDs.
        Handles chunking of long content automatically.
        """
        # Skip terminal noise
        if chunk.content_type == ContentType.TERMINAL and chunk.is_terminal_noise():
            logger.debug("Skipping terminal noise: %s", chunk.content[:40])
            return []

        # Split long content into sub-chunks
        texts = chunk_text(chunk.content)
        if not texts:
            return []

        stored_ids = []
        for i, text in enumerate(texts):
            sub = chunk.model_copy(update={"content": text})
            if len(texts) > 1:
                # Give each sub-chunk a stable unique ID
                import hashlib, uuid
                seed = f"{chunk.id}-{i}"
                sub = sub.model_copy(
                    update={"id": uuid.UUID(hashlib.md5(seed.encode()).hexdigest())}
                )

            chunk_id = await self._store_one(sub)
            if chunk_id:
                stored_ids.append(chunk_id)
                await self._context_queue.put(chunk_id)

        return stored_ids

    async def _store_one(self, chunk: Chunk) -> str | None:
        """Store a single chunk. Returns chunk_id or None if duplicate."""
        if self._vector.hash_exists(chunk.content_hash):
            logger.debug("Duplicate, skipping: %s", chunk.content_hash[:12])
            return None

        # Embed
        [embedding] = embed([chunk.content])

        # Save to all three stores
        self._vector.add(chunk, embedding)
        self._meta.save(chunk)
        await self._blobs.put(
            str(chunk.id),
            json.dumps(chunk.model_dump(mode="json")).encode(),
        )

        logger.info("Stored %s [%s]", chunk.id, chunk.content_type)
        return str(chunk.id)

    async def run_context_estimation(self) -> None:
        """
        Background coroutine — consume the context queue and enrich chunks.
        Run this as a long-lived task alongside the daemon.
        """
        while True:
            chunk_id = await self._context_queue.get()
            try:
                record = self._meta.get(chunk_id)
                if record and not record.context_estimated_at:
                    estimate = await self._llm.estimate_context(
                        record.content, record.content_type
                    )
                    if estimate.summary:
                        self._meta.update_context(
                            chunk_id, estimate.summary, estimate.activity_tags
                        )
                        logger.debug("Context estimated for %s: %s", chunk_id, estimate.summary)
            except Exception:
                logger.exception("Context estimation failed for %s", chunk_id)
            finally:
                self._context_queue.task_done()

    def search(self, query: str, limit: int = 10, content_types: list[str] | None = None) -> list[dict]:
        """Embed query and return ranked results with full content."""
        [embedding] = embed([query])
        results = self._vector.search_with_filter(embedding, content_types, limit)
        # Enrich results with full content from metadata store
        enriched = []
        for r in results:
            record = self._meta.get(r["id"])
            if record:
                enriched.append({
                    **r,
                    "content": record.content,
                    "activity_summary": record.activity_summary,
                    "working_directory": record.working_directory,
                })
        return enriched
