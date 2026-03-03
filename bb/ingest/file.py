"""File importer — handles `bb import <path>` and file watcher events."""

from __future__ import annotations

import mimetypes
import socket
from pathlib import Path

from bb.core.chunk import Chunk, ContentType
from bb.ingest.pipeline import IngestPipeline

# Extensions and MIME prefixes we can meaningfully index as text
_TEXT_SUFFIXES = {
    ".md", ".txt", ".rst", ".org",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".htm",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".conf", ".env",
    ".sh", ".bash", ".zsh", ".fish",
    ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".rb", ".php",
    ".sql", ".graphql", ".proto",
    ".csv", ".tsv", ".log",
    ".tex", ".bib",
    ".xml", ".svg",
}


def is_text_file(path: Path) -> bool:
    """Return True if the file can be meaningfully indexed as text."""
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("text/"):
        return True
    return False


def detect_content_type(path: Path) -> ContentType:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".rst", ".org"}:
        return ContentType.NOTE
    return ContentType.FILE


class UnsupportedFileType(ValueError):
    pass


async def import_file(path: Path, pipeline: IngestPipeline, tags: list[str] | None = None) -> list[str]:
    """
    Import a single text file into the brain.
    Raises UnsupportedFileType for images, binaries, etc.
    Returns list of stored chunk IDs.
    """
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ValueError(f"{path} is not a file")

    if not is_text_file(path):
        raise UnsupportedFileType(
            f"'{path.name}' is not a supported text file type. "
            "big-brain indexes text — images, PDFs, and binaries are not supported yet."
        )

    content = path.read_text(errors="replace")
    if not content.strip():
        return []

    chunk = Chunk(
        content=content,
        content_type=detect_content_type(path),
        source_node=socket.gethostname(),
        origin_path=str(path),
        tags=tags or [],
        key_path="personal",
    )
    return await pipeline.ingest(chunk)


async def import_path(
    path: Path,
    pipeline: IngestPipeline,
    tags: list[str] | None = None,
    recursive: bool = False,
) -> list[str]:
    """Import a file or directory. Returns all stored chunk IDs."""
    path = path.resolve()
    if path.is_file():
        return await import_file(path, pipeline, tags)
    if path.is_dir():
        all_ids: list[str] = []
        glob = path.rglob("*") if recursive else path.glob("*")
        for child in glob:
            if child.is_file() and not child.name.startswith("."):
                try:
                    ids = await import_file(child, pipeline, tags)
                    all_ids.extend(ids)
                except Exception:
                    pass
        return all_ids
    raise FileNotFoundError(path)
