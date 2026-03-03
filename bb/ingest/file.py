"""File importer — handles `bb import <path>` and file watcher events."""

from __future__ import annotations

import base64
import mimetypes
import socket
from pathlib import Path

import httpx

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

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

_IMAGE_PROMPT = (
    "Describe this image in detail for a personal knowledge base. "
    "Include any visible text, people, objects, colors, setting, and context. "
    "Be specific and thorough so the description is useful for semantic search."
)


def is_text_file(path: Path) -> bool:
    """Return True if the file can be meaningfully indexed as text."""
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("text/"):
        return True
    return False


def is_image_file(path: Path) -> bool:
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    return bool(mime and mime.startswith("image/"))


def detect_content_type(path: Path) -> ContentType:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".rst", ".org"}:
        return ContentType.NOTE
    return ContentType.FILE


class UnsupportedFileType(ValueError):
    pass


def describe_image(path: Path, base_url: str, model: str) -> str:
    """Call llava via Ollama to get a text description of an image."""
    image_b64 = base64.b64encode(path.read_bytes()).decode()
    try:
        resp = httpx.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": _IMAGE_PROMPT, "images": [image_b64], "stream": False},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["response"].strip()
    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot describe image '{path.name}': Ollama is not running at {base_url}. "
            "Start Ollama first."
        )


async def import_file(path: Path, pipeline: IngestPipeline, tags: list[str] | None = None) -> list[str]:
    """
    Import a single file into the brain.
    - Text files are chunked and embedded directly.
    - Image files are described by llava and the description is indexed.
    - Other binary files raise UnsupportedFileType.
    Returns list of stored chunk IDs.
    """
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ValueError(f"{path} is not a file")

    if is_image_file(path):
        cfg = pipeline._settings.llm
        base_url = cfg.base_url or "http://localhost:11434"
        description = describe_image(path, base_url, cfg.ollama_vision_model)
        if not description:
            return []
        chunk = Chunk(
            content=description,
            content_type=ContentType.IMAGE,
            source_node=socket.gethostname(),
            origin_path=str(path),
            tags=tags or [],
            key_path="personal",
        )
        return await pipeline.ingest(chunk)

    if not is_text_file(path):
        raise UnsupportedFileType(
            f"'{path.name}' is not a supported file type. "
            "big-brain indexes text files and images (jpg, png, gif, webp)."
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
