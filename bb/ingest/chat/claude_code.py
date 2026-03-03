"""Claude Code chat importer.

Walks ~/.claude/projects/ (or a custom path) and ingests every conversation
message as a CHAT_CLAUDE chunk.  Each message (user or assistant) becomes its
own chunk so the pipeline's chunker can handle long assistant replies.

Format reference: each session is a JSONL file where relevant lines have
  type = "user" | "assistant"
  message.role = "user" | "assistant"
  message.content = list of content blocks, {type: "text", text: "..."}
  uuid, timestamp (ISO-8601), cwd, sessionId
"""
from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bb.ingest.pipeline import IngestPipeline

logger = logging.getLogger(__name__)


def _parse_text_content(content) -> str:
    """Extract concatenated text from a message content field.

    Handles both string content and list-of-blocks format.
    Skips non-text blocks (tool_use, tool_result, thinking, etc.).
    """
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _iter_messages(jsonl_path: Path):
    """Yield (role, text, timestamp_dt, cwd, message_uuid) from a session file."""
    with jsonl_path.open(encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") not in ("user", "assistant"):
                continue

            message = obj.get("message", {})
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue

            text = _parse_text_content(message.get("content", []))
            if not text:
                continue

            # Parse timestamp
            ts_str = obj.get("timestamp", "")
            ts: datetime | None = None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(
                        tzinfo=None
                    )
                except ValueError:
                    pass

            cwd = obj.get("cwd") or ""
            msg_uuid = obj.get("uuid") or ""
            yield role, text, ts, cwd, msg_uuid


async def import_claude_code(
    pipeline: IngestPipeline,
    projects_dir: Path | None = None,
    since: datetime | None = None,
) -> list[str]:
    """Walk projects_dir and ingest all Claude Code conversation messages.

    Args:
        pipeline: The ingest pipeline.
        projects_dir: Root of Claude Code project storage.
                      Defaults to ~/.claude/projects/.
        since: Skip messages older than this datetime (naive UTC).

    Returns:
        List of stored chunk IDs.
    """
    from bb.core.chunk import Chunk, ContentType

    if projects_dir is None:
        projects_dir = Path.home() / ".claude" / "projects"

    if not projects_dir.exists():
        logger.warning("Claude Code projects dir not found: %s", projects_dir)
        return []

    source_node = socket.gethostname()
    all_ids: list[str] = []

    for proj_dir in sorted(projects_dir.iterdir()):
        if not proj_dir.is_dir():
            continue

        for jsonl_file in sorted(proj_dir.glob("*.jsonl")):
            # Fast-path: skip the whole file if it's older than --since
            if since is not None:
                mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
                if mtime < since:
                    continue

            session_id = jsonl_file.stem
            msg_count = 0

            for role, text, ts, cwd, msg_uuid in _iter_messages(jsonl_file):
                # Per-message --since filter using the message's own timestamp
                if since is not None and ts is not None:
                    if ts < since:
                        continue

                origin = f"{jsonl_file}#{msg_uuid}" if msg_uuid else str(jsonl_file)

                chunk = Chunk(
                    content=text,
                    content_type=ContentType.CHAT_CLAUDE,
                    source_node=source_node,
                    origin_path=origin,
                    working_directory=cwd or None,
                    tags=["claude-code", role],
                    key_path="personal",
                )
                if ts is not None:
                    chunk = chunk.model_copy(update={"timestamp": ts})

                ids = await pipeline.ingest(chunk)
                all_ids.extend(ids)
                msg_count += len(ids)

            if msg_count:
                logger.info(
                    "claude_code: %s → %d chunk(s) stored [session %s]",
                    proj_dir.name,
                    msg_count,
                    session_id[:8],
                )

    return all_ids
