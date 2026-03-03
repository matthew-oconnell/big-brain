"""Smoke tests for the core ingest pipeline."""

import asyncio
import socket
import tempfile
from pathlib import Path

import pytest

from bb.core.chunk import Chunk, ContentType
from bb.core.config import Settings, StorageConfig
from bb.ingest.pipeline import IngestPipeline


def make_settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.storage = StorageConfig(data_dir=tmp_path)
    return s


@pytest.fixture
def pipeline(tmp_path):
    settings = make_settings(tmp_path)
    return IngestPipeline(settings)


def make_chunk(content: str, content_type: ContentType = ContentType.THOUGHT) -> Chunk:
    return Chunk(
        content=content,
        content_type=content_type,
        source_node=socket.gethostname(),
    )


@pytest.mark.asyncio
async def test_ingest_and_search(pipeline):
    chunk = make_chunk("The HKDF key derivation function is used to derive encryption keys.")
    ids = await pipeline.ingest(chunk)
    assert len(ids) == 1

    results = pipeline.search("key derivation encryption", limit=5)
    assert any("HKDF" in r["content"] for r in results)


@pytest.mark.asyncio
async def test_deduplication(pipeline):
    chunk = make_chunk("This is a unique thought about federation.")
    ids1 = await pipeline.ingest(chunk)
    ids2 = await pipeline.ingest(chunk)
    assert len(ids1) == 1
    assert len(ids2) == 0  # duplicate, skipped


@pytest.mark.asyncio
async def test_terminal_noise_skipped(pipeline):
    chunk = make_chunk("ls", ContentType.TERMINAL)
    ids = await pipeline.ingest(chunk)
    assert len(ids) == 0


@pytest.mark.asyncio
async def test_long_content_chunked(pipeline):
    # Use distinct paragraphs so dedup doesn't collapse them into one stored chunk.
    long_text = "\n\n".join(
        f"Paragraph {i} about CFD simulations and fluid dynamics. " * 20
        for i in range(5)
    )
    chunk = make_chunk(long_text, ContentType.FILE)
    ids = await pipeline.ingest(chunk)
    assert len(ids) > 1  # should have been split
