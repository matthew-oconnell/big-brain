"""Tests for bb/ingest/file.py — file detection and import."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bb.ingest.file import (
    FILE_STORE_MAX,
    UnsupportedFileType,
    detect_content_type,
    import_file,
    is_image_file,
    is_text_file,
)
from bb.core.chunk import ContentType
from tests.conftest import make_settings
from bb.ingest.pipeline import IngestPipeline


# ── Detection helpers ──────────────────────────────────────────────────────────

class TestIsTextFile:
    def test_markdown(self, tmp_path: Path):
        assert is_text_file(tmp_path / "readme.md") is True

    def test_python(self, tmp_path: Path):
        assert is_text_file(tmp_path / "main.py") is True

    def test_rust(self, tmp_path: Path):
        assert is_text_file(tmp_path / "main.rs") is True

    def test_yaml(self, tmp_path: Path):
        assert is_text_file(tmp_path / "config.yaml") is True

    def test_toml(self, tmp_path: Path):
        assert is_text_file(tmp_path / "pyproject.toml") is True

    def test_csv(self, tmp_path: Path):
        assert is_text_file(tmp_path / "data.csv") is True

    def test_jpeg_is_not_text(self, tmp_path: Path):
        assert is_text_file(tmp_path / "photo.jpg") is False

    def test_binary_extension_is_not_text(self, tmp_path: Path):
        assert is_text_file(tmp_path / "archive.tar") is False


class TestIsImageFile:
    def test_jpeg(self, tmp_path: Path):
        assert is_image_file(tmp_path / "photo.jpg") is True

    def test_jpeg_uppercase(self, tmp_path: Path):
        assert is_image_file(tmp_path / "photo.JPEG") is True

    def test_png(self, tmp_path: Path):
        assert is_image_file(tmp_path / "icon.png") is True

    def test_gif(self, tmp_path: Path):
        assert is_image_file(tmp_path / "anim.gif") is True

    def test_webp(self, tmp_path: Path):
        assert is_image_file(tmp_path / "pic.webp") is True

    def test_python_is_not_image(self, tmp_path: Path):
        assert is_image_file(tmp_path / "main.py") is False

    def test_pdf_is_not_image(self, tmp_path: Path):
        assert is_image_file(tmp_path / "doc.pdf") is False


class TestDetectContentType:
    def test_markdown_is_note(self, tmp_path: Path):
        assert detect_content_type(tmp_path / "notes.md") == ContentType.NOTE

    def test_txt_is_note(self, tmp_path: Path):
        assert detect_content_type(tmp_path / "journal.txt") == ContentType.NOTE

    def test_python_is_file(self, tmp_path: Path):
        assert detect_content_type(tmp_path / "main.py") == ContentType.FILE

    def test_json_is_file(self, tmp_path: Path):
        assert detect_content_type(tmp_path / "config.json") == ContentType.FILE


# ── import_file ────────────────────────────────────────────────────────────────

class TestImportFile:
    @pytest.fixture
    def pipeline(self, tmp_path: Path) -> IngestPipeline:
        return IngestPipeline(make_settings(tmp_path / "data"))

    @pytest.mark.asyncio
    async def test_import_text_file(self, pipeline: IngestPipeline, tmp_path: Path):
        f = tmp_path / "notes.md"
        f.write_text("# My Notes\n\nThis is about semantic search and embeddings.")
        ids = await import_file(f, pipeline)
        assert len(ids) >= 1

    @pytest.mark.asyncio
    async def test_import_text_searchable(self, pipeline: IngestPipeline, tmp_path: Path):
        f = tmp_path / "notes.md"
        f.write_text("The quick brown fox jumps over the lazy dog.")
        await import_file(f, pipeline)
        results = pipeline.search("fox jumps lazy dog", limit=5)
        assert any("fox" in r["content"] for r in results)

    @pytest.mark.asyncio
    async def test_import_empty_file_returns_empty(self, pipeline: IngestPipeline, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("   \n\n  ")
        ids = await import_file(f, pipeline)
        assert ids == []

    @pytest.mark.asyncio
    async def test_unsupported_file_type_raises(self, pipeline: IngestPipeline, tmp_path: Path):
        f = tmp_path / "archive.tar"
        f.write_bytes(b"\x00" * 100)
        with pytest.raises(UnsupportedFileType):
            await import_file(f, pipeline)

    @pytest.mark.asyncio
    async def test_missing_file_raises_file_not_found(self, pipeline: IngestPipeline, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            await import_file(tmp_path / "does_not_exist.py", pipeline)

    @pytest.mark.asyncio
    async def test_origin_path_override(self, pipeline: IngestPipeline, tmp_path: Path):
        f = tmp_path / "actual_file.md"
        f.write_text("Content about override paths.")
        await import_file(f, pipeline, origin_path="original_name.md")
        # Check meta store has correct origin_path
        records = pipeline._meta.today()
        assert any(r.origin_path == "original_name.md" for r in records)

    @pytest.mark.asyncio
    async def test_python_file_content_type_is_file(self, pipeline: IngestPipeline, tmp_path: Path):
        f = tmp_path / "script.py"
        f.write_text("def hello():\n    return 'world'\n")
        await import_file(f, pipeline)
        records = pipeline._meta.today()
        assert any(r.content_type == ContentType.FILE.value for r in records)

    @pytest.mark.asyncio
    async def test_tags_stored(self, pipeline: IngestPipeline, tmp_path: Path):
        import json
        f = tmp_path / "tagged.md"
        f.write_text("Tagged content for testing.")
        await import_file(f, pipeline, tags=["test-tag", "important"])
        records = pipeline._meta.today()
        tagged = [r for r in records if "test-tag" in json.loads(r.tags)]
        assert len(tagged) >= 1

    @pytest.mark.asyncio
    async def test_image_without_ollama_raises_runtime_error(
        self, pipeline: IngestPipeline, tmp_path: Path
    ):
        """import_file propagates RuntimeError raised by describe_image (e.g. Ollama down)."""
        from unittest.mock import patch as mock_patch

        f = tmp_path / "photo.jpg"
        f.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0] + [0] * 100))
        with mock_patch(
            "bb.ingest.file.describe_image",
            side_effect=RuntimeError("Ollama is not running at http://localhost:11434"),
        ):
            with pytest.raises(RuntimeError, match="Ollama"):
                await import_file(f, pipeline)

    @pytest.mark.asyncio
    async def test_import_idempotent(self, pipeline: IngestPipeline, tmp_path: Path):
        f = tmp_path / "notes.md"
        f.write_text("Idempotent import test content.")
        ids1 = await import_file(f, pipeline)
        ids2 = await import_file(f, pipeline)
        assert len(ids1) >= 1
        assert len(ids2) == 0  # dedup — already stored
