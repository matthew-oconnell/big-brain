"""Tests for bb/api/mcp.py — MCP tool functions.

These tests mock the _get/_post helpers so no daemon is needed.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from bb.api.mcp import (
    _daemon_error,
    _fmt_results,
    add_thought,
    get_by_date,
    get_recent_context,
    get_stats,
    search_brain,
)


# ── Formatting helpers ─────────────────────────────────────────────────────────

class TestFmtResults:
    def test_empty_returns_no_results(self):
        result = _fmt_results([])
        assert result == "No results found."

    def test_single_result_formatted(self):
        items = [
            {
                "content_type": "thought",
                "timestamp": "2026-01-15T10:30:00",
                "preview": "This is a test thought.",
                "score": 0.95,
            }
        ]
        result = _fmt_results(items, show_score=True)
        assert "thought" in result
        assert "2026-01-15 10:30" in result
        assert "test thought" in result
        assert "95%" in result

    def test_working_directory_shown(self):
        items = [
            {
                "content_type": "terminal",
                "timestamp": "2026-01-15T10:00:00",
                "preview": "git status",
                "working_directory": "/home/user/project",
            }
        ]
        result = _fmt_results(items)
        assert "/home/user/project" in result

    def test_origin_path_shown_when_no_working_dir(self):
        items = [
            {
                "content_type": "file",
                "timestamp": "2026-01-15T10:00:00",
                "preview": "some file content",
                "working_directory": None,
                "origin_path": "/home/user/notes.md",
            }
        ]
        result = _fmt_results(items)
        assert "notes.md" in result

    def test_long_preview_truncated(self):
        items = [
            {
                "content_type": "thought",
                "timestamp": "2026-01-15T10:00:00",
                "preview": "word " * 100,
            }
        ]
        result = _fmt_results(items)
        assert "…" in result or len(result) < 1000

    def test_score_hidden_by_default(self):
        items = [
            {
                "content_type": "thought",
                "timestamp": "2026-01-15T10:00:00",
                "preview": "test",
                "score": 0.99,
            }
        ]
        result = _fmt_results(items, show_score=False)
        assert "99%" not in result


class TestDaemonError:
    def test_connect_error_message(self):
        e = httpx.ConnectError("refused")
        result = _daemon_error(e)
        assert "daemon" in result.lower()
        assert "bb daemon start" in result

    def test_generic_error_message(self):
        e = ValueError("something went wrong")
        result = _daemon_error(e)
        assert "Daemon error" in result


# ── search_brain ───────────────────────────────────────────────────────────────

class TestSearchBrain:
    def test_no_results(self):
        with patch("bb.api.mcp._get", return_value=[]):
            result = search_brain("obscure query that matches nothing")
        assert "No results found" in result

    def test_with_results(self):
        mock_results = [
            {
                "content_type": "thought",
                "timestamp": "2026-01-15T10:00:00",
                "content": "This is about machine learning.",
                "activity_summary": None,
                "score": 0.85,
                "working_directory": None,
                "origin_path": None,
            }
        ]
        with patch("bb.api.mcp._get", return_value=mock_results):
            result = search_brain("machine learning")
        assert "1 found" in result
        assert "machine learning" in result

    def test_header_includes_query(self):
        with patch("bb.api.mcp._get", return_value=[]):
            result = search_brain("my specific query")
        assert "my specific query" in result

    def test_content_type_filter_in_header(self):
        with patch("bb.api.mcp._get", return_value=[]):
            result = search_brain("query", content_types="terminal,thought")
        assert "terminal,thought" in result

    def test_limit_capped_at_30(self):
        captured_params = {}

        def fake_get(path, **params):
            captured_params.update(params)
            return []

        with patch("bb.api.mcp._get", side_effect=fake_get):
            search_brain("test", limit=100)

        assert captured_params.get("limit") == 30

    def test_daemon_connect_error(self):
        with patch("bb.api.mcp._get", side_effect=httpx.ConnectError("refused")):
            result = search_brain("test")
        assert "daemon" in result.lower()

    def test_uses_activity_summary_over_content(self):
        mock_results = [
            {
                "content_type": "terminal",
                "timestamp": "2026-01-15T10:00:00",
                "content": "raw terminal command",
                "activity_summary": "User ran tests and reviewed output",
                "score": 0.9,
                "working_directory": "/home/user",
                "origin_path": None,
            }
        ]
        with patch("bb.api.mcp._get", return_value=mock_results):
            result = search_brain("tests")
        assert "User ran tests" in result


# ── add_thought ────────────────────────────────────────────────────────────────

class TestAddThought:
    def test_success(self):
        with patch("bb.api.mcp._post", return_value={"stored": 1, "ids": ["abc12345def"]}):
            result = add_thought("My important idea")
        assert "Stored" in result
        assert "abc12345" in result

    def test_duplicate(self):
        with patch("bb.api.mcp._post", return_value={"stored": 0, "ids": []}):
            result = add_thought("Already stored content")
        assert "Duplicate" in result

    def test_tags_parsed_correctly(self):
        captured_body = {}

        def fake_post(path, body):
            captured_body.update(body)
            return {"stored": 1, "ids": ["abc"]}

        with patch("bb.api.mcp._post", side_effect=fake_post):
            add_thought("tagged content", tags="research,cfd,todo")

        assert captured_body.get("tags") == ["research", "cfd", "todo"]

    def test_invalid_thought_type_defaults_to_thought(self):
        captured_body = {}

        def fake_post(path, body):
            captured_body.update(body)
            return {"stored": 1, "ids": ["abc"]}

        with patch("bb.api.mcp._post", side_effect=fake_post):
            add_thought("content", thought_type="invalid_type")

        assert captured_body.get("content_type") == "thought"

    def test_valid_types_accepted(self):
        for valid_type in ["thought", "journal", "note"]:
            captured = {}

            def fake_post(path, body):
                captured.update(body)
                return {"stored": 1, "ids": ["x"]}

            with patch("bb.api.mcp._post", side_effect=fake_post):
                add_thought("content", thought_type=valid_type)

            assert captured.get("content_type") == valid_type

    def test_daemon_error(self):
        with patch("bb.api.mcp._post", side_effect=httpx.ConnectError("refused")):
            result = add_thought("test")
        assert "daemon" in result.lower()


# ── get_recent_context ─────────────────────────────────────────────────────────

class TestGetRecentContext:
    def test_returns_header_with_item_count(self):
        mock_items = [
            {
                "content_type": "thought",
                "timestamp": "2026-03-02T10:00:00",
                "preview": "Recent activity",
            }
        ]
        with patch("bb.api.mcp._get", return_value=mock_items):
            result = get_recent_context(hours=2.0)
        assert "2h" in result
        assert "1 items" in result

    def test_empty_result(self):
        with patch("bb.api.mcp._get", return_value=[]):
            result = get_recent_context(hours=6.0)
        assert "No results found" in result

    def test_hours_clamped_minimum(self):
        captured = {}

        def fake_get(path, **params):
            captured.update(params)
            return []

        with patch("bb.api.mcp._get", side_effect=fake_get):
            get_recent_context(hours=0.0)

        assert captured.get("hours") >= 0.5

    def test_hours_clamped_maximum(self):
        captured = {}

        def fake_get(path, **params):
            captured.update(params)
            return []

        with patch("bb.api.mcp._get", side_effect=fake_get):
            get_recent_context(hours=1000.0)

        assert captured.get("hours") <= 72.0

    def test_daemon_error(self):
        with patch("bb.api.mcp._get", side_effect=httpx.ConnectError("refused")):
            result = get_recent_context()
        assert "daemon" in result.lower()


# ── get_by_date ────────────────────────────────────────────────────────────────

class TestGetByDate:
    def test_invalid_date_format(self):
        result = get_by_date("not-a-date")
        assert "Invalid date" in result

    def test_valid_date_with_results(self):
        mock_items = [
            {
                "content_type": "thought",
                "timestamp": "2026-03-01T14:00:00",
                "preview": "Something on that day",
            }
        ]
        with patch("bb.api.mcp._get", return_value=mock_items):
            result = get_by_date("2026-03-01")
        assert "2026-03-01" in result
        assert "1 items" in result

    def test_valid_date_no_results(self):
        with patch("bb.api.mcp._get", return_value=[]):
            result = get_by_date("2020-01-01")
        assert "No results found" in result

    def test_daemon_error(self):
        with patch("bb.api.mcp._get", side_effect=httpx.ConnectError("refused")):
            result = get_by_date("2026-03-01")
        assert "daemon" in result.lower()


# ── get_stats ──────────────────────────────────────────────────────────────────

class TestGetStats:
    def test_basic_structure(self):
        mock_digest = {
            "date": "2026-03-02",
            "total": 42,
            "by_type": {"thought": 20, "terminal": 15, "chat_claude": 7},
            "samples": [
                {
                    "content_type": "thought",
                    "timestamp": "2026-03-02T09:00:00",
                    "preview": "Morning idea",
                }
            ],
        }
        with patch("bb.api.mcp._get", return_value=mock_digest):
            result = get_stats()
        assert "2026-03-02" in result
        assert "42" in result
        assert "thought" in result
        assert "terminal" in result

    def test_empty_brain(self):
        mock_digest = {"date": "2026-03-02", "total": 0, "by_type": {}, "samples": []}
        with patch("bb.api.mcp._get", return_value=mock_digest):
            result = get_stats()
        assert "0" in result

    def test_daemon_error(self):
        with patch("bb.api.mcp._get", side_effect=httpx.ConnectError("refused")):
            result = get_stats()
        assert "daemon" in result.lower()
