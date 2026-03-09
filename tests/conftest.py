"""Shared fixtures for big-brain tests."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from bb.core.chunk import Chunk, ContentType
from bb.core.config import Settings, StorageConfig
from bb.ingest.pipeline import IngestPipeline


def make_settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.storage = StorageConfig(data_dir=tmp_path)
    return s


def make_chunk(
    content: str,
    content_type: ContentType = ContentType.THOUGHT,
    tags: list[str] | None = None,
) -> Chunk:
    return Chunk(
        content=content,
        content_type=content_type,
        source_node=socket.gethostname(),
        tags=tags or [],
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def pipeline(tmp_path: Path) -> IngestPipeline:
    return IngestPipeline(make_settings(tmp_path))
