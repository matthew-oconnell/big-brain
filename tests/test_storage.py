"""Tests for storage backends: LocalBlobStore, MetaStore, VectorStore."""

from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from bb.core.chunk import Chunk, ContentType
from bb.storage.blob.local import LocalBlobStore
from bb.storage.meta import MetaStore
from tests.conftest import make_chunk, make_settings


# ── LocalBlobStore ─────────────────────────────────────────────────────────────

class TestLocalBlobStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> LocalBlobStore:
        return LocalBlobStore(tmp_path / "blobs")

    @pytest.mark.asyncio
    async def test_put_and_get(self, store: LocalBlobStore):
        data = b"hello world"
        await store.put("mykey", data)
        result = await store.get("mykey")
        assert result == data

    @pytest.mark.asyncio
    async def test_get_missing_raises_key_error(self, store: LocalBlobStore):
        with pytest.raises(KeyError):
            await store.get("nonexistent")

    @pytest.mark.asyncio
    async def test_exists_true(self, store: LocalBlobStore):
        await store.put("exists-key", b"data")
        assert await store.exists("exists-key") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, store: LocalBlobStore):
        assert await store.exists("missing-key") is False

    @pytest.mark.asyncio
    async def test_delete(self, store: LocalBlobStore):
        await store.put("del-key", b"data")
        await store.delete("del-key")
        assert await store.exists("del-key") is False

    @pytest.mark.asyncio
    async def test_delete_missing_is_noop(self, store: LocalBlobStore):
        # Should not raise
        await store.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_list_keys(self, store: LocalBlobStore):
        # Keys are stored sharded by first 2 chars; list_keys matches on filename only.
        # Use simple UUID-style keys (no slashes) to match real usage.
        await store.put("abc-1111", b"1")
        await store.put("abc-2222", b"2")
        await store.put("xyz-3333", b"3")
        keys = list(await store.list_keys("abc-"))
        assert set(keys) == {"abc-1111", "abc-2222"}

    @pytest.mark.asyncio
    async def test_list_keys_empty_prefix(self, store: LocalBlobStore):
        await store.put("foo-aaa", b"1")
        await store.put("bar-bbb", b"2")
        keys = list(await store.list_keys(""))
        assert "foo-aaa" in keys
        assert "bar-bbb" in keys

    @pytest.mark.asyncio
    async def test_binary_data_roundtrip(self, store: LocalBlobStore):
        data = bytes(range(256)) * 100
        await store.put("binary-key", data)
        result = await store.get("binary-key")
        assert result == data

    @pytest.mark.asyncio
    async def test_overwrite(self, store: LocalBlobStore):
        await store.put("key", b"first")
        await store.put("key", b"second")
        result = await store.get("key")
        assert result == b"second"


# ── MetaStore ──────────────────────────────────────────────────────────────────

def _make_chunk_record(content: str, content_type: str = "thought") -> Chunk:
    return Chunk(
        content=content,
        content_type=ContentType(content_type),
        source_node=socket.gethostname(),
    )


class TestMetaStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> MetaStore:
        return MetaStore(tmp_path)

    def test_save_and_get(self, store: MetaStore):
        chunk = _make_chunk_record("test content")
        store.save(chunk)
        record = store.get(str(chunk.id))
        assert record is not None
        assert record.content == "test content"
        assert record.content_type == "thought"

    def test_get_missing_returns_none(self, store: MetaStore):
        result = store.get("00000000-0000-0000-0000-000000000000")
        assert result is None

    def test_update_context(self, store: MetaStore):
        chunk = _make_chunk_record("need context")
        store.save(chunk)
        store.update_context(str(chunk.id), "AI summary here", ["tag1", "tag2"])
        record = store.get(str(chunk.id))
        assert record is not None
        assert record.activity_summary == "AI summary here"
        assert json.loads(record.activity_tags) == ["tag1", "tag2"]
        assert record.context_estimated_at is not None

    def test_pending_context_estimation(self, store: MetaStore):
        chunk1 = _make_chunk_record("needs context 1")
        chunk2 = _make_chunk_record("needs context 2")
        store.save(chunk1)
        store.save(chunk2)
        store.update_context(str(chunk1.id), "done", [])

        pending = store.pending_context_estimation()
        ids = [r.id for r in pending]
        assert str(chunk2.id) in ids
        assert str(chunk1.id) not in ids

    def test_today(self, store: MetaStore):
        chunk = _make_chunk_record("today's content")
        store.save(chunk)
        records = store.today()
        ids = [r.id for r in records]
        assert str(chunk.id) in ids

    def test_by_date(self, store: MetaStore):
        from datetime import date

        chunk = _make_chunk_record("past content")
        # Fake a timestamp in the past
        past = datetime(2020, 6, 15, 12, 0, 0)
        from bb.storage.meta import ChunkRecord
        from sqlmodel import Session
        record = ChunkRecord(
            id=str(chunk.id),
            content=chunk.content,
            content_type=chunk.content_type.value,
            source_node=chunk.source_node,
            timestamp=past,
            tags="[]",
            activity_tags="[]",
            content_hash=chunk.content_hash,
            key_path=chunk.key_path,
        )
        with Session(store._engine) as session:
            session.merge(record)
            session.commit()

        results = store.by_date(date(2020, 6, 15))
        assert any(r.id == str(chunk.id) for r in results)

        results_other = store.by_date(date(2020, 6, 16))
        assert not any(r.id == str(chunk.id) for r in results_other)

    def test_since(self, store: MetaStore):
        chunk = _make_chunk_record("recent content")
        store.save(chunk)

        cutoff_before = datetime.utcnow() - timedelta(hours=1)
        results = store.since(cutoff_before)
        assert any(r.id == str(chunk.id) for r in results)

        cutoff_after = datetime.utcnow() + timedelta(hours=1)
        results = store.since(cutoff_after)
        assert not any(r.id == str(chunk.id) for r in results)

    def test_mark_synced(self, store: MetaStore):
        chunk = _make_chunk_record("sync me")
        store.save(chunk)
        unsynced_ids = [r.id for r in store.unsynced()]
        assert str(chunk.id) in unsynced_ids

        store.mark_synced(str(chunk.id))
        unsynced_ids = [r.id for r in store.unsynced()]
        assert str(chunk.id) not in unsynced_ids

    def test_save_idempotent(self, store: MetaStore):
        chunk = _make_chunk_record("same content")
        store.save(chunk)
        store.save(chunk)  # second save uses merge — should not duplicate
        results = store.today()
        matches = [r for r in results if r.id == str(chunk.id)]
        assert len(matches) == 1
