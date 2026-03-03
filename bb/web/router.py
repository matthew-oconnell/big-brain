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
    "image":       "#e879f9",  # fuchsia
}


def _pipeline():
    from bb.api.daemon import get_pipeline
    return get_pipeline()


def _enrich_records(raw: list[dict]) -> list[dict]:
    """Fetch full content for a list of vector results."""
    pipeline = _pipeline()
    out = []
    for r in raw:
        # Ensure we have an ID
        vid = r.get("id") or r.get("_id")
        if not vid:
            continue
            
        record = pipeline._meta.get(vid)
        if record:
            preview = (record.activity_summary or record.content[:250]).replace("\n", " ")
            out.append({
                "id": vid,
                "content_type": r.get("content_type") or record.content_type,
                "color": TYPE_COLORS.get(r.get("content_type") or record.content_type, "#8b949e"),
                "timestamp": r.get("timestamp", "")[:16].replace("T", " "),
                "preview": preview,
                "working_directory": record.working_directory,
                "origin_path": record.origin_path,
                "source_node": record.source_node,
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
            "id": r["id"],
            "content_type": r["content_type"],
            "color": TYPE_COLORS.get(r["content_type"], "#8b949e"),
            "timestamp": r.get("timestamp", "")[:16].replace("T", " "),
            "preview": preview,
            "working_directory": r.get("working_directory"),
            "origin_path": r.get("origin_path") or None,
            "source_node": r.get("source_node", ""),
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


@router.get("/web/test", response_class=HTMLResponse)
async def web_test(request: Request):
    """Simple test endpoint to verify routing works."""
    return "<h1>Router is working!</h1>"


@router.get("/web/debug/entries")
async def debug_entries():
    """Debug endpoint to see what's in the database."""
    pipeline = _pipeline()
    # Get recent from vector store
    vector_recent = pipeline._vector.recent(5)
    
    # Try to look up each one in meta store
    details = []
    for v in vector_recent:
        vid = v.get("id")
        meta = pipeline._meta.get(vid) if vid else None
        details.append({
            "vector_id": vid,
            "vector_fields": list(v.keys()),
            "meta_found": meta is not None,
            "meta_id": str(meta.id) if meta else None,
        })
    
    return {"total": len(vector_recent), "samples": details}


@router.get("/web/detail/{chunk_id}", response_class=HTMLResponse)
async def web_detail(request: Request, chunk_id: str):
    """Fetch full chunk details for a modal view."""
    import json
    import logging
    
    logger = logging.getLogger(__name__)
    pipeline = _pipeline()
    
    # Try to get the record
    record = pipeline._meta.get(chunk_id)
    logger.info(f"Detail lookup: chunk_id={chunk_id}, found={record is not None}")
    
    if not record:
        # Try URL-decoded version in case there's encoding issue
        from urllib.parse import unquote
        chunk_id_decoded = unquote(chunk_id)
        if chunk_id_decoded != chunk_id:
            record = pipeline._meta.get(chunk_id_decoded)
            logger.info(f"Retry with decoded: chunk_id={chunk_id_decoded}, found={record is not None}")
        
        if not record:
            # Return 200 with error template (don't use 404 as it overrides the response)
            return templates.TemplateResponse("partials/detail.html", {
                "request": request,
                "found": False,
                "error": f"Entry not found",
            })
    
    # Parse JSON fields
    try:
        tags = json.loads(record.tags) if record.tags else []
    except (json.JSONDecodeError, TypeError):
        tags = []
    
    try:
        activity_tags = json.loads(record.activity_tags) if record.activity_tags else []
    except (json.JSONDecodeError, TypeError):
        activity_tags = []
    
    return templates.TemplateResponse("partials/detail.html", {
        "request": request,
        "found": True,
        "chunk_id": chunk_id,
        "content": record.content,
        "content_type": record.content_type,
        "timestamp": record.timestamp.isoformat(),
        "timestamp_display": record.timestamp.strftime("%Y-%m-%d %H:%M"),
        "source_node": record.source_node,
        "origin_path": record.origin_path,
        "working_directory": record.working_directory,
        "tags": tags,
        "activity_summary": record.activity_summary,
        "activity_tags": activity_tags,
        "exit_code": record.exit_code,
        "color": TYPE_COLORS.get(record.content_type, "#8b949e"),
    })


@router.post("/web/upload")
async def web_upload(file: UploadFile = File(...)):
    from bb.ingest.file import UnsupportedFileType, import_file

    original_name = file.filename or "upload.txt"
    suffix = Path(original_name).suffix or ".txt"
    content = await file.read()

    # Use original filename in temp dir so origin_path is meaningful
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / original_name
        tmp_path.write_bytes(content)
        try:
            ids = await import_file(tmp_path, _pipeline(), origin_path=original_name)
            return JSONResponse({"stored": len(ids), "filename": original_name, "chunks": len(ids)})
        except UnsupportedFileType as e:
            return JSONResponse({"stored": 0, "filename": original_name, "chunks": 0, "error": str(e)}, status_code=415)
        except Exception as e:
            return JSONResponse({"stored": 0, "filename": original_name, "chunks": 0, "error": str(e)}, status_code=500)
