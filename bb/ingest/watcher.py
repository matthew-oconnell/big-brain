"""
File system watcher — auto-ingests new and modified files from watched directories.
Runs as a background asyncio task inside the daemon.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from bb.ingest.pipeline import IngestPipeline

logger = logging.getLogger(__name__)

# Extensions to ignore (binary, build artifacts, hidden files, etc.)
IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".bz2",
    ".pdf",  # TODO: add PDF text extraction later
}


def _should_ingest(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    if path.suffix.lower() in IGNORE_EXTENSIONS:
        return False
    if any(part.startswith(".") for part in path.parts):
        return False
    return path.is_file()


class _BrainEventHandler(FileSystemEventHandler):
    """Watchdog event handler — posts events to an asyncio queue."""

    def __init__(self, queue: asyncio.Queue[Path], loop: asyncio.AbstractEventLoop) -> None:
        self._queue = queue
        self._loop = loop

    def _enqueue(self, path_str: str) -> None:
        path = Path(path_str)
        if _should_ingest(path):
            # Thread-safe: watchdog runs in a separate thread
            self._loop.call_soon_threadsafe(self._queue.put_nowait, path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(str(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(str(event.src_path))


async def run_watcher(watch_dirs: list[Path], pipeline: IngestPipeline) -> None:
    """
    Long-running coroutine that watches directories and ingests changed files.
    Designed to run as a background asyncio task.
    """
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[Path] = asyncio.Queue()

    handler = _BrainEventHandler(queue, loop)
    observer = Observer()

    for directory in watch_dirs:
        if directory.exists():
            observer.schedule(handler, str(directory), recursive=True)
            logger.info("Watching %s", directory)
        else:
            logger.warning("Watch directory does not exist: %s", directory)

    observer.start()
    logger.info("File watcher started for %d director(ies)", len(watch_dirs))

    try:
        while True:
            path = await queue.get()
            try:
                from bb.ingest.file import import_file
                ids = await import_file(path, pipeline)
                if ids:
                    logger.info("Auto-ingested %s → %d chunk(s)", path.name, len(ids))
            except Exception:
                logger.exception("Failed to ingest %s", path)
            finally:
                queue.task_done()
    except asyncio.CancelledError:
        observer.stop()
        observer.join()
        logger.info("File watcher stopped")
