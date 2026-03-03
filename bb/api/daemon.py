"""
big-brain daemon — FastAPI server running on localhost:7777.

Handles all ingest from shell hooks, the CLI, and the file watcher.
Runs LLM context estimation in the background.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from bb.core.chunk import Chunk, ContentType
from bb.core.config import Settings

logger = logging.getLogger(__name__)

# Module-level pipeline, initialised in lifespan
_pipeline = None


def get_pipeline():
    if _pipeline is None:
        raise RuntimeError("Pipeline not initialised")
    return _pipeline


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline
    from bb.ingest.pipeline import IngestPipeline

    settings = Settings.load()
    _pipeline = IngestPipeline(settings)

    # Background: LLM context estimation queue
    ctx_task = asyncio.create_task(_pipeline.run_context_estimation())

    # Background: file watcher (if watch_dirs configured)
    watch_task = None
    if settings.watch_dirs:
        from bb.ingest.watcher import run_watcher
        watch_task = asyncio.create_task(run_watcher(settings.watch_dirs, _pipeline))

    logger.info("big-brain daemon started on port %s", settings.daemon.port)
    yield

    ctx_task.cancel()
    if watch_task:
        watch_task.cancel()


app = FastAPI(title="big-brain", lifespan=lifespan)

from bb.web.router import router as web_router  # noqa: E402
app.include_router(web_router)


# ── Request / Response models ─────────────────────────────────────────────────

class TerminalIngestRequest(BaseModel):
    cmd: str
    cwd: str = ""
    exit_code: int = 0


class ThoughtIngestRequest(BaseModel):
    content: str
    tags: list[str] = []
    content_type: str = "thought"
    key_path: str = "personal"


class FileIngestRequest(BaseModel):
    path: str
    tags: list[str] = []
    recursive: bool = False


class IngestResponse(BaseModel):
    stored: int
    ids: list[str]


class SearchResult(BaseModel):
    id: str
    content_type: str
    timestamp: str
    score: float
    content: str
    activity_summary: str | None
    working_directory: str | None
    origin_path: str | None


# ── Ingest endpoints ──────────────────────────────────────────────────────────

@app.post("/ingest/terminal", response_model=IngestResponse)
async def ingest_terminal(req: TerminalIngestRequest):
    chunk = Chunk(
        content=req.cmd,
        content_type=ContentType.TERMINAL,
        source_node=socket.gethostname(),
        working_directory=req.cwd or None,
        exit_code=req.exit_code,
        key_path="personal/terminal",
    )
    ids = await get_pipeline().ingest(chunk)
    return IngestResponse(stored=len(ids), ids=ids)


@app.post("/ingest/thought", response_model=IngestResponse)
async def ingest_thought(req: ThoughtIngestRequest):
    chunk = Chunk(
        content=req.content,
        content_type=ContentType(req.content_type),
        source_node=socket.gethostname(),
        tags=req.tags,
        key_path=req.key_path,
    )
    ids = await get_pipeline().ingest(chunk)
    return IngestResponse(stored=len(ids), ids=ids)


@app.post("/ingest/file", response_model=IngestResponse)
async def ingest_file(req: FileIngestRequest):
    from bb.ingest.file import import_path
    path = Path(req.path).expanduser().resolve()
    try:
        ids = await import_path(path, get_pipeline(), tags=req.tags, recursive=req.recursive)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    return IngestResponse(stored=len(ids), ids=ids)


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/search", response_model=list[SearchResult])
async def search(
    q: str,
    limit: int = 10,
    types: str = "",  # comma-separated content types
):
    content_types = [t.strip() for t in types.split(",") if t.strip()] or None
    results = get_pipeline().search(q, limit=limit, content_types=content_types)
    return [
        SearchResult(
            id=r["id"],
            content_type=r["content_type"],
            timestamp=r.get("timestamp", ""),
            score=max(0.0, 1.0 - r.get("_distance", 0.0) / 2.0),
            content=r.get("content", ""),
            activity_summary=r.get("activity_summary"),
            working_directory=r.get("working_directory"),
            origin_path=r.get("origin_path") or None,
        )
        for r in results
    ]


# ── Recent ────────────────────────────────────────────────────────────────────

@app.get("/recent")
async def recent(limit: int = 20, types: str = "") -> list[dict[str, Any]]:
    pipeline = get_pipeline()
    results = pipeline._vector.recent(limit)
    out = []
    for r in results:
        record = pipeline._meta.get(r["id"])
        if not record:
            continue  # skip orphaned vector entries with no meta record
        out.append({
            "id": r["id"],
            "content_type": r["content_type"],
            "timestamp": r.get("timestamp", ""),
            "preview": (record.activity_summary or record.content[:120]).replace("\n", " "),
            "origin_path": r.get("origin_path", ""),
        })
    return out


# ── Digest ────────────────────────────────────────────────────────────────────

@app.get("/digest")
async def digest() -> dict[str, Any]:
    pipeline = get_pipeline()
    today_records = pipeline._meta.today()
    by_type: dict[str, int] = {}
    samples: list[dict] = []
    for record in today_records:
        by_type[record.content_type] = by_type.get(record.content_type, 0) + 1
        if len(samples) < 5:
            samples.append({
                "content_type": record.content_type,
                "preview": (record.activity_summary or record.content[:100]).replace("\n", " "),
                "timestamp": record.timestamp.isoformat(),
            })
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "total": len(today_records),
        "by_type": by_type,
        "samples": samples,
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, Any]:
    from bb.core.config import Settings
    settings = Settings.load()
    return {
        "status": "ok",
        "node_id": settings.node_id,
        "llm_provider": settings.llm.provider,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def run(host: str = "127.0.0.1", port: int = 7777) -> None:
    import os
    port = int(os.environ.get("BB_DAEMON_PORT", port))
    host = os.environ.get("BB_DAEMON_HOST", host)
    uvicorn.run(
        "bb.api.daemon:app",
        host=host,
        port=port,
        log_level="warning",
        reload=False,
    )


if __name__ == "__main__":
    run()
