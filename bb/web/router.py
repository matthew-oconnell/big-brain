"""Web UI router — search, add thoughts, drag-and-drop file import."""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

TYPE_COLORS: dict[str, str] = {
    "terminal":    "#3fb950",  # green
    "thought":     "#bc8cff",  # purple
    "journal":     "#e3b341",  # amber
    "file":        "#79c0ff",  # light blue
    "chat_claude": "#f0883e",  # orange
    "chat_vscode": "#58a6ff",  # blue
    "email":       "#ff7b72",  # red
    "note":        "#56d364",  # light green
}


def _pipeline():
    from bb.api.daemon import get_pipeline
    return get_pipeline()


def _enrich_records(raw: list[dict]) -> list[dict]:
    """Fetch full content for a list of vector results."""
    pipeline = _pipeline()
    out = []
    for r in raw:
        record = pipeline._meta.get(r["id"])
        if record:
            preview = (record.activity_summary or record.content[:250]).replace("\n", " ")
            out.append({
                "content_type": r["content_type"],
                "color": TYPE_COLORS.get(r["content_type"], "#8b949e"),
                "timestamp": r.get("timestamp", "")[:16].replace("T", " "),
                "preview": preview,
                "working_directory": record.working_directory,
                "origin_path": record.origin_path,
                "score": None,
            })
    return out


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    pipeline = _pipeline()
    from bb.core.config import Settings
    settings = Settings.load()
    recent = _enrich_records(pipeline._vector.recent(20))
    return templates.TemplateResponse("index.html", {
        "request": request,
        "node_id": settings.node_id,
        "results": recent,
        "query": "",
    })


# ── HTMX partials ─────────────────────────────────────────────────────────────

@router.get("/web/search", response_class=HTMLResponse)
async def web_search(request: Request, q: str = ""):
    pipeline = _pipeline()
    if not q.strip():
        # Empty query → return recent items (same template, no query)
        recent = _enrich_records(pipeline._vector.recent(20))
        return templates.TemplateResponse("partials/results.html", {
            "request": request,
            "results": recent,
            "query": "",
        })

    raw = pipeline.search(q.strip(), limit=15)
    results = []
    for r in raw:
        preview = (r.get("activity_summary") or r.get("content", "")[:250]).replace("\n", " ")
        results.append({
            "content_type": r["content_type"],
            "color": TYPE_COLORS.get(r["content_type"], "#8b949e"),
            "timestamp": r.get("timestamp", "")[:16].replace("T", " "),
            "preview": preview,
            "working_directory": r.get("working_directory"),
            "origin_path": r.get("origin_path") or None,
            "score": f"{max(0.0, 1.0 - r.get('_distance', 0.0) / 2.0):.0%}",
        })
    return templates.TemplateResponse("partials/results.html", {
        "request": request,
        "results": results,
        "query": q,
    })


@router.post("/web/thought", response_class=HTMLResponse)
async def web_add_thought(
    request: Request,
    content: str = Form(...),
    tags: str = Form(""),
    content_type: str = Form("thought"),
):
    from bb.core.chunk import Chunk, ContentType

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        ct = ContentType(content_type)
    except ValueError:
        ct = ContentType.THOUGHT

    chunk = Chunk(
        content=content.strip(),
        content_type=ct,
        source_node=socket.gethostname(),
        tags=tag_list,
        key_path="personal",
    )
    ids = await _pipeline().ingest(chunk)
    return templates.TemplateResponse("partials/thought_saved.html", {
        "request": request,
        "stored": len(ids),
        "preview": content[:80],
    })


@router.post("/web/upload")
async def web_upload(file: UploadFile = File(...)):
    from bb.ingest.file import import_file

    original_name = file.filename or "upload.txt"
    suffix = Path(original_name).suffix or ".txt"
    content = await file.read()

    # Use original filename in temp dir so origin_path is meaningful
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / original_name
        tmp_path.write_bytes(content)
        try:
            ids = await import_file(tmp_path, _pipeline())
            return JSONResponse({"stored": len(ids), "filename": original_name, "chunks": len(ids)})
        except Exception as e:
            return JSONResponse({"stored": 0, "filename": original_name, "chunks": 0, "error": str(e)})
