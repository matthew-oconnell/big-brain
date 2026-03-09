"""Tests for bb/ingest/chat/ importers (Claude Code and VSCode)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from bb.ingest.chat.claude_code import (
    _parse_text_content,
    _iter_messages,
    import_claude_code,
)
from bb.ingest.chat.vscode import (
    _extract_user_text,
    _extract_assistant_text,
    _workspace_folder,
    import_vscode,
)
from tests.conftest import make_settings
from bb.ingest.pipeline import IngestPipeline


# ── Claude Code: unit helpers ──────────────────────────────────────────────────

class TestParseTextContent:
    def test_string_content_returned_stripped(self):
        assert _parse_text_content("  hello  ") == "hello"

    def test_list_of_text_blocks_concatenated(self):
        blocks = [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ]
        result = _parse_text_content(blocks)
        assert "first" in result
        assert "second" in result

    def test_tool_use_blocks_skipped(self):
        blocks = [
            {"type": "text", "text": "visible"},
            {"type": "tool_use", "name": "bash", "input": {"command": "ls"}},
        ]
        result = _parse_text_content(blocks)
        assert result == "visible"
        assert "bash" not in result

    def test_thinking_blocks_skipped(self):
        blocks = [
            {"type": "thinking", "thinking": "internal thought"},
            {"type": "text", "text": "output"},
        ]
        result = _parse_text_content(blocks)
        assert result == "output"
        assert "internal thought" not in result

    def test_empty_list_returns_empty(self):
        assert _parse_text_content([]) == ""

    def test_non_list_non_str_returns_empty(self):
        assert _parse_text_content(42) == ""  # type: ignore[arg-type]
        assert _parse_text_content(None) == ""  # type: ignore[arg-type]


class TestIterMessages:
    def _write_jsonl(self, path: Path, lines: list[dict]) -> None:
        with path.open("w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    def test_yields_user_and_assistant_messages(self, tmp_path: Path):
        session_file = tmp_path / "session.jsonl"
        self._write_jsonl(session_file, [
            {
                "type": "user",
                "message": {"role": "user", "content": "Hello!"},
                "timestamp": "2026-01-15T10:00:00Z",
                "cwd": "/home/user/project",
                "uuid": "uuid-1",
            },
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": "Hi there!"},
                "timestamp": "2026-01-15T10:00:01Z",
                "cwd": "/home/user/project",
                "uuid": "uuid-2",
            },
        ])
        messages = list(_iter_messages(session_file))
        assert len(messages) == 2
        roles = [m[0] for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_skips_non_message_types(self, tmp_path: Path):
        session_file = tmp_path / "session.jsonl"
        self._write_jsonl(session_file, [
            {"type": "summary", "content": "ignored"},
            {"type": "user", "message": {"role": "user", "content": "real"}, "uuid": "u1"},
        ])
        messages = list(_iter_messages(session_file))
        assert len(messages) == 1
        assert messages[0][1] == "real"

    def test_skips_empty_content(self, tmp_path: Path):
        session_file = tmp_path / "session.jsonl"
        self._write_jsonl(session_file, [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "bash"}],
                },
                "uuid": "u1",
            },
        ])
        messages = list(_iter_messages(session_file))
        assert len(messages) == 0

    def test_skips_invalid_json_lines(self, tmp_path: Path):
        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            'not valid json\n'
            '{"type":"user","message":{"role":"user","content":"ok"},"uuid":"u1"}\n'
        )
        messages = list(_iter_messages(session_file))
        assert len(messages) == 1

    def test_timestamp_parsed_correctly(self, tmp_path: Path):
        session_file = tmp_path / "session.jsonl"
        self._write_jsonl(session_file, [
            {
                "type": "user",
                "message": {"role": "user", "content": "hi"},
                "timestamp": "2026-01-15T10:30:00Z",
                "uuid": "u1",
            },
        ])
        messages = list(_iter_messages(session_file))
        role, text, ts, cwd, uuid = messages[0]
        assert ts == datetime(2026, 1, 15, 10, 30, 0)


# ── Claude Code: integration ───────────────────────────────────────────────────

def _make_fake_projects_dir(base: Path) -> Path:
    """Create a minimal fake ~/.claude/projects/ layout."""
    projects_dir = base / "projects"
    proj = projects_dir / "project-abc"
    proj.mkdir(parents=True)

    session_file = proj / "session-001.jsonl"
    lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": "What is vector search?"},
            "timestamp": "2026-01-15T10:00:00Z",
            "cwd": "/home/user/project",
            "uuid": "msg-1",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Vector search uses embeddings."}],
            },
            "timestamp": "2026-01-15T10:00:01Z",
            "cwd": "/home/user/project",
            "uuid": "msg-2",
        },
    ]
    with session_file.open("w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    return projects_dir


class TestImportClaudeCode:
    @pytest.mark.asyncio
    async def test_basic_import(self, tmp_path: Path):
        projects_dir = _make_fake_projects_dir(tmp_path)
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        ids = await import_claude_code(pipeline, projects_dir=projects_dir)
        assert len(ids) == 2  # user + assistant message

    @pytest.mark.asyncio
    async def test_missing_projects_dir_returns_empty(self, tmp_path: Path):
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        ids = await import_claude_code(pipeline, projects_dir=tmp_path / "nonexistent")
        assert ids == []

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_path: Path):
        projects_dir = _make_fake_projects_dir(tmp_path)
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        ids1 = await import_claude_code(pipeline, projects_dir=projects_dir)
        ids2 = await import_claude_code(pipeline, projects_dir=projects_dir)
        assert len(ids1) == 2
        assert len(ids2) == 0  # dedup — already stored

    @pytest.mark.asyncio
    async def test_since_filter_excludes_old_messages(self, tmp_path: Path):
        projects_dir = _make_fake_projects_dir(tmp_path)
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        # Since 2027 — all 2026 messages should be excluded
        future = datetime(2027, 1, 1)
        ids = await import_claude_code(pipeline, projects_dir=projects_dir, since=future)
        assert ids == []

    @pytest.mark.asyncio
    async def test_since_filter_includes_new_messages(self, tmp_path: Path):
        projects_dir = _make_fake_projects_dir(tmp_path)
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        # Since 2025 — all 2026 messages should be included
        past = datetime(2025, 1, 1)
        ids = await import_claude_code(pipeline, projects_dir=projects_dir, since=past)
        assert len(ids) == 2

    @pytest.mark.asyncio
    async def test_content_type_is_chat_claude(self, tmp_path: Path):
        from bb.core.chunk import ContentType
        projects_dir = _make_fake_projects_dir(tmp_path)
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        await import_claude_code(pipeline, projects_dir=projects_dir)
        results = pipeline.search("vector search embeddings", limit=5)
        assert all(r["content_type"] == ContentType.CHAT_CLAUDE.value for r in results)


# ── VSCode: unit helpers ───────────────────────────────────────────────────────

class TestExtractUserText:
    def test_basic_text_parts(self):
        message = {"parts": [{"text": "hello"}, {"text": "world"}]}
        assert _extract_user_text(message) == "hello\nworld"

    def test_empty_parts(self):
        assert _extract_user_text({}) == ""
        assert _extract_user_text({"parts": []}) == ""

    def test_strips_whitespace(self):
        message = {"parts": [{"text": "  hi  "}]}
        assert _extract_user_text(message) == "hi"


class TestExtractAssistantText:
    def test_markdown_content_kind(self):
        response = [
            {"kind": "markdownContent", "value": {"value": "This is the answer."}}
        ]
        result = _extract_assistant_text(response)
        assert result == "This is the answer."

    def test_null_kind_with_string_value(self):
        response = [
            {"kind": None, "value": "plain text response"}
        ]
        result = _extract_assistant_text(response)
        assert result == "plain text response"

    def test_mixed_kinds(self):
        response = [
            {"kind": "markdownContent", "value": {"value": "part 1"}},
            {"kind": None, "value": "part 2"},
        ]
        result = _extract_assistant_text(response)
        assert "part 1" in result
        assert "part 2" in result

    def test_empty_response(self):
        assert _extract_assistant_text([]) == ""

    def test_skips_non_dict_items(self):
        response = ["not a dict", {"kind": None, "value": "valid"}]
        result = _extract_assistant_text(response)
        assert result == "valid"


class TestWorkspaceFolder:
    def test_reads_folder_from_json(self, tmp_path: Path):
        ws = tmp_path / "workspace.json"
        ws.write_text(json.dumps({"folder": "file:///home/user/myproject"}))
        assert _workspace_folder(tmp_path) == "/home/user/myproject"

    def test_missing_file_returns_none(self, tmp_path: Path):
        assert _workspace_folder(tmp_path) is None

    def test_invalid_json_returns_none(self, tmp_path: Path):
        ws = tmp_path / "workspace.json"
        ws.write_text("not json")
        assert _workspace_folder(tmp_path) is None

    def test_missing_folder_key_returns_none(self, tmp_path: Path):
        ws = tmp_path / "workspace.json"
        ws.write_text(json.dumps({"other": "value"}))
        assert _workspace_folder(tmp_path) is None


# ── VSCode: integration ────────────────────────────────────────────────────────

def _make_fake_workspace_storage(base: Path) -> Path:
    """Create a minimal fake VSCode workspaceStorage layout."""
    storage = base / "workspaceStorage"
    ws_dir = storage / "abc123hash"
    ws_dir.mkdir(parents=True)

    # workspace.json
    (ws_dir / "workspace.json").write_text(
        json.dumps({"folder": "file:///home/user/myproject"})
    )

    # chatSessions/<session>.json
    chat_sessions = ws_dir / "chatSessions"
    chat_sessions.mkdir()
    session = {
        "sessionId": "sess-001",
        "requests": [
            {
                "requestId": "req-1",
                "timestamp": 1737000000000,  # 2025-01-16 ish
                "message": {"parts": [{"text": "How do I use async/await?"}]},
                "response": [
                    {"kind": "markdownContent", "value": {"value": "Use async def and await."}}
                ],
            }
        ],
    }
    (chat_sessions / "sess-001.json").write_text(json.dumps(session))

    return storage


class TestImportVscode:
    @pytest.mark.asyncio
    async def test_basic_import(self, tmp_path: Path):
        storage = _make_fake_workspace_storage(tmp_path)
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        ids = await import_vscode(pipeline, workspace_storage=storage)
        assert len(ids) == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_empty_storage_returns_empty(self, tmp_path: Path):
        empty_storage = tmp_path / "empty_storage"
        empty_storage.mkdir()
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        ids = await import_vscode(pipeline, workspace_storage=empty_storage)
        assert ids == []

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_path: Path):
        storage = _make_fake_workspace_storage(tmp_path)
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        ids1 = await import_vscode(pipeline, workspace_storage=storage)
        ids2 = await import_vscode(pipeline, workspace_storage=storage)
        assert len(ids1) == 2
        assert len(ids2) == 0

    @pytest.mark.asyncio
    async def test_content_type_is_chat_vscode(self, tmp_path: Path):
        from bb.core.chunk import ContentType
        storage = _make_fake_workspace_storage(tmp_path)
        pipeline = IngestPipeline(make_settings(tmp_path / "data"))
        await import_vscode(pipeline, workspace_storage=storage)
        results = pipeline.search("async await", limit=5)
        assert all(r["content_type"] == ContentType.CHAT_VSCODE.value for r in results)
