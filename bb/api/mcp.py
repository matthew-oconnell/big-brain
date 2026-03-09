"""
big-brain MCP server — exposes your second brain to any MCP-compatible AI tool.

Transport: stdio (Claude Code starts this as a subprocess).
Data layer: wraps the daemon at http://localhost:7777 — no direct storage access.

Tools:
  search_brain       — semantic search across all stored knowledge
  add_thought        — capture a new thought without leaving the conversation
  get_recent_context — what has been captured in the last N hours
  get_by_date        — retrieve a specific day's activity
  get_stats          — counts and summary of what's in the brain
"""
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timedelta

import httpx
from mcp.server.fastmcp import FastMCP

DAEMON_URL = "http://127.0.0.1:7777"
TIMEOUT = 10.0

mcp = FastMCP("big-brain")


# ── helpers ───────────────────────────────────────────────────────────────────

def _get(path: str, **params) -> dict | list:
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(f"{DAEMON_URL}{path}", params=params)
        r.raise_for_status()
        return r.json()


def _post(path: str, body: dict) -> dict:
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(f"{DAEMON_URL}{path}", json=body)
        r.raise_for_status()
        return r.json()


def _daemon_error(e: Exception) -> str:
    if isinstance(e, httpx.ConnectError):
        return (
            "Cannot reach big-brain daemon. "
            "Start it with: bb daemon start"
        )
    return f"Daemon error: {e}"


def _fmt_results(items: list[dict], show_score: bool = False) -> str:
    if not items:
        return "No results found."
    lines = []
    for r in items:
        ts = r.get("timestamp", "")[:16].replace("T", " ")
        ctype = r.get("content_type", "")
        preview = r.get("preview") or r.get("content", "")
        preview = preview.replace("\n", " ").strip()
        preview = textwrap.shorten(preview, width=200, placeholder="…")
        score = f"  ({r['score']:.0%})" if show_score and "score" in r else ""
        wd = r.get("working_directory") or ""
        origin = r.get("origin_path") or ""

        lines.append(f"[{ctype}] {ts}{score}")
        lines.append(f"  {preview}")
        if wd:
            lines.append(f"  📁 {wd}")
        elif origin:
            short = origin.split("#")[0]  # strip #uuid fragment
            lines.append(f"  📄 {short}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ── tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def search_brain(
    query: str,
    limit: int = 10,
    content_types: str = "",
) -> str:
    """Search your second brain by meaning using semantic (vector) search.

    Args:
        query: Natural language search query.
        limit: Maximum number of results to return (default 10, max 30).
        content_types: Comma-separated filter, e.g. "terminal,chat_claude".
                       Leave empty to search all types.
    """
    try:
        results = _get(
            "/search",
            q=query,
            limit=min(limit, 30),
            types=content_types,
        )
    except Exception as e:
        return _daemon_error(e)

    header = f"Search results for '{query}'"
    if content_types:
        header += f" (types: {content_types})"
    header += f" — {len(results)} found\n"

    formatted = _fmt_results(
        [
            {
                "content_type": r["content_type"],
                "timestamp": r["timestamp"],
                "preview": r.get("activity_summary") or r.get("content", ""),
                "score": r["score"],
                "working_directory": r.get("working_directory"),
                "origin_path": r.get("origin_path"),
            }
            for r in results
        ],
        show_score=True,
    )
    return header + formatted


@mcp.tool()
def add_thought(
    content: str,
    tags: str = "",
    thought_type: str = "thought",
) -> str:
    """Capture a new thought, note, or idea into your second brain.

    Args:
        content: The text to store.
        tags: Comma-separated tags, e.g. "research,cfd,todo".
        thought_type: One of: thought, journal, note (default: thought).
    """
    valid_types = {"thought", "journal", "note"}
    if thought_type not in valid_types:
        thought_type = "thought"

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    try:
        result = _post(
            "/ingest/thought",
            {"content": content, "tags": tag_list, "content_type": thought_type},
        )
    except Exception as e:
        return _daemon_error(e)

    stored = result.get("stored", 0)
    if stored:
        chunk_id = result.get("ids", [""])[0][:8]
        return f"Stored [{thought_type}] {chunk_id}…\n  {content[:120]}"
    return "Duplicate — this content is already in your brain."


@mcp.tool()
def get_recent_context(hours: float = 6.0) -> str:
    """Retrieve what has been captured in the last N hours.

    Useful for priming context: 'what was I working on this afternoon?'

    Args:
        hours: How many hours back to look (default 6, max 72).
    """
    hours = min(max(hours, 0.5), 72.0)
    try:
        items = _get("/since", hours=hours)
    except Exception as e:
        return _daemon_error(e)

    cutoff = datetime.now() - timedelta(hours=hours)
    header = f"Activity in the last {hours:g}h (since {cutoff.strftime('%Y-%m-%d %H:%M')}) — {len(items)} items\n"
    return header + _fmt_results(items)


@mcp.tool()
def get_by_date(date: str) -> str:
    """Retrieve all captured activity for a specific calendar date.

    Args:
        date: Date in YYYY-MM-DD format, e.g. '2026-03-01'.
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return "Invalid date format. Use YYYY-MM-DD."

    try:
        items = _get("/by_date", date=date)
    except Exception as e:
        return _daemon_error(e)

    header = f"Activity on {date} — {len(items)} items\n"
    return header + _fmt_results(items)


@mcp.tool()
def get_stats() -> str:
    """Get a summary of what's in your brain: counts by type, today's activity.

    Returns an overview useful for understanding what has been captured.
    """
    try:
        digest = _get("/digest")
    except Exception as e:
        return _daemon_error(e)

    date = digest.get("date", "today")
    total = digest.get("total", 0)
    by_type: dict = digest.get("by_type", {})
    samples: list = digest.get("samples", [])

    lines = [f"Brain activity for {date} — {total} items captured today\n"]

    if by_type:
        lines.append("By type:")
        for ctype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  {ctype:<16} {count}")
        lines.append("")

    if samples:
        lines.append("Recent samples:")
        for s in samples:
            ts = s.get("timestamp", "")[:16].replace("T", " ")
            preview = s.get("preview", "").replace("\n", " ")[:120]
            lines.append(f"  {ts}  [{s.get('content_type','')}]  {preview}")

    return "\n".join(lines)


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    mcp.run()  # stdio transport — Claude Code starts this as a subprocess


if __name__ == "__main__":
    main()
