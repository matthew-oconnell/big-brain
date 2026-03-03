"""VSCode Copilot / Cursor chat importer.

Walks ~/.config/Code/User/workspaceStorage/ and ingests chat sessions stored
as JSON files under each workspace's chatSessions/ subdirectory.

Format reference (VSCode built-in Copilot chat):
  workspaceStorage/<hash>/workspace.json  → {"folder": "file:///path/to/project"}
  workspaceStorage/<hash>/chatSessions/<session-id>.json
    {
      "requests": [
        {
          "requestId": "...",
          "timestamp": 1234567890123,   ← Unix milliseconds
          "message": {"parts": [{"text": "..."}]},
          "response": [
            {"kind": "markdownContent", "value": {"value": "..."}},
            {"kind": null, "value": "..."},
            ...
          ]
        }
      ]
    }
"""
from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from bb.ingest.pipeline import IngestPipeline

logger = logging.getLogger(__name__)

_WORKSPACE_STORAGE_PATHS = [
    Path.home() / ".config" / "Code" / "User" / "workspaceStorage",
    Path.home() / ".config" / "Code - OSS" / "User" / "workspaceStorage",
    Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage",
]


def _workspace_folder(workspace_dir: Path) -> str | None:
    """Read the project folder path from workspace.json."""
    ws_json = workspace_dir / "workspace.json"
    if not ws_json.exists():
        return None
    try:
        data = json.loads(ws_json.read_text())
        folder = data.get("folder", "")
        if folder.startswith("file://"):
            return urlparse(folder).path
        return folder or None
    except (json.JSONDecodeError, OSError):
        return None


def _extract_user_text(message: dict) -> str:
    """Extract plain text from a VSCode request message object."""
    parts = message.get("parts", [])
    texts = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text", "").strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _extract_assistant_text(response: list) -> str:
    """Extract plain text from a VSCode response item list."""
    texts = []
    for item in response:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        value = item.get("value", "")
        if kind == "markdownContent":
            # value is {"value": "...", "isTrusted": ...}
            if isinstance(value, dict):
                text = value.get("value", "").strip()
            else:
                text = str(value).strip()
            if text:
                texts.append(text)
        elif kind is None and isinstance(value, str):
            text = value.strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _iter_requests(session_path: Path):
    """Yield (user_text, assistant_text, timestamp_dt, session_id) from a session file."""
    try:
        data = json.loads(session_path.read_text())
    except (json.JSONDecodeError, OSError):
        return

    session_id = data.get("sessionId", session_path.stem)

    for req in data.get("requests", []):
        if not isinstance(req, dict):
            continue

        # User message
        user_text = _extract_user_text(req.get("message", {}))

        # Assistant response
        assistant_text = _extract_assistant_text(req.get("response", []))

        if not user_text and not assistant_text:
            continue

        # Timestamp: Unix milliseconds
        ts: datetime | None = None
        ts_ms = req.get("timestamp")
        if ts_ms:
            try:
                ts = datetime.fromtimestamp(int(ts_ms) / 1000.0)
            except (ValueError, OSError):
                pass

        yield user_text, assistant_text, ts, session_id


async def import_vscode(
    pipeline: IngestPipeline,
    workspace_storage: Path | None = None,
    since: datetime | None = None,
) -> list[str]:
    """Walk VSCode workspace storage and ingest all chat session messages.

    Args:
        pipeline: The ingest pipeline.
        workspace_storage: Root workspace storage directory.
                           Defaults to scanning standard paths.
        since: Skip messages older than this datetime.

    Returns:
        List of stored chunk IDs.
    """
    from bb.core.chunk import Chunk, ContentType

    if workspace_storage is not None:
        roots = [workspace_storage]
    else:
        roots = [p for p in _WORKSPACE_STORAGE_PATHS if p.exists()]

    if not roots:
        logger.warning("No VSCode workspace storage directory found")
        return []

    source_node = socket.gethostname()
    all_ids: list[str] = []

    for root in roots:
        for workspace_dir in sorted(root.iterdir()):
            if not workspace_dir.is_dir():
                continue

            chat_sessions_dir = workspace_dir / "chatSessions"
            if not chat_sessions_dir.is_dir():
                continue

            project_folder = _workspace_folder(workspace_dir)

            for session_file in sorted(chat_sessions_dir.glob("*.json")):
                # Fast-path: skip old files
                if since is not None:
                    mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                    if mtime < since:
                        continue

                for user_text, assistant_text, ts, session_id in _iter_requests(session_file):
                    # Per-message --since filter
                    if since is not None and ts is not None:
                        if ts < since:
                            continue

                    origin = str(session_file)

                    for role, text in (("user", user_text), ("assistant", assistant_text)):
                        if not text:
                            continue

                        chunk = Chunk(
                            content=text,
                            content_type=ContentType.CHAT_VSCODE,
                            source_node=source_node,
                            origin_path=origin,
                            working_directory=project_folder,
                            tags=["vscode", role],
                            key_path="personal",
                        )
                        if ts is not None:
                            chunk = chunk.model_copy(update={"timestamp": ts})

                        ids = await pipeline.ingest(chunk)
                        all_ids.extend(ids)

    return all_ids
