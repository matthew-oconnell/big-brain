"""Tests for the FastAPI daemon endpoints (bb/api/daemon.py).

Uses httpx.ASGITransport to call the ASGI app directly without starting a server.
The lifespan is bypassed — _pipeline is injected manually before each test.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bb.api.daemon import app
from bb.ingest.pipeline import IngestPipeline
from tests.conftest import make_chunk, make_settings
from bb.core.chunk import ContentType


@pytest.fixture
async def client(tmp_path: Path):
    """ASGI test client with a real pipeline injected, bypassing the lifespan."""
    import bb.api.daemon as daemon_module

    settings = make_settings(tmp_path)
    pipeline = IngestPipeline(settings)
    daemon_module._pipeline = pipeline

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    daemon_module._pipeline = None


# ── Health ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client: httpx.AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "node_id" in data
    assert "llm_provider" in data


# ── Ingest: thought ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_thought(client: httpx.AsyncClient):
    r = await client.post(
        "/ingest/thought",
        json={"content": "This is a test thought about neural networks."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["stored"] == 1
    assert len(data["ids"]) == 1


@pytest.mark.asyncio
async def test_ingest_thought_with_tags(client: httpx.AsyncClient):
    r = await client.post(
        "/ingest/thought",
        json={"content": "Tagged thought about CFD simulations.", "tags": ["cfd", "research"]},
    )
    assert r.status_code == 200
    assert r.json()["stored"] == 1


@pytest.mark.asyncio
async def test_ingest_thought_dedup(client: httpx.AsyncClient):
    payload = {"content": "Dedup test thought — should only be stored once."}
    r1 = await client.post("/ingest/thought", json=payload)
    r2 = await client.post("/ingest/thought", json=payload)
    assert r1.json()["stored"] == 1
    assert r2.json()["stored"] == 0


# ── Ingest: terminal ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_terminal_noise_skipped(client: httpx.AsyncClient):
    r = await client.post(
        "/ingest/terminal",
        json={"cmd": "ls", "cwd": "/home/user", "exit_code": 0},
    )
    assert r.status_code == 200
    # "ls" is noise — should be filtered
    assert r.json()["stored"] == 0


@pytest.mark.asyncio
async def test_ingest_terminal_meaningful(client: httpx.AsyncClient):
    r = await client.post(
        "/ingest/terminal",
        json={
            "cmd": "pytest tests/ -v --cov=bb --cov-report=html",
            "cwd": "/home/user/project",
            "exit_code": 0,
        },
    )
    assert r.status_code == 200
    assert r.json()["stored"] == 1


# ── Search ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_returns_results(client: httpx.AsyncClient):
    # Ingest first
    await client.post(
        "/ingest/thought",
        json={"content": "Quantum computing uses qubits for computation."},
    )
    r = await client.get("/search", params={"q": "quantum qubits"})
    assert r.status_code == 200
    results = r.json()
    assert isinstance(results, list)
    assert len(results) >= 1
    assert "content_type" in results[0]
    assert "score" in results[0]


@pytest.mark.asyncio
async def test_search_empty_brain_returns_empty(client: httpx.AsyncClient):
    r = await client.get("/search", params={"q": "nothing here"})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_search_type_filter(client: httpx.AsyncClient):
    await client.post(
        "/ingest/thought",
        json={"content": "Test filtering by content type works correctly."},
    )
    r = await client.get(
        "/search", params={"q": "content type filter", "types": "thought"}
    )
    assert r.status_code == 200
    results = r.json()
    for result in results:
        assert result["content_type"] == "thought"


# ── Recent ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recent_returns_list(client: httpx.AsyncClient):
    await client.post(
        "/ingest/thought",
        json={"content": "Something recent to retrieve in the recent endpoint."},
    )
    r = await client.get("/recent")
    assert r.status_code == 200
    results = r.json()
    assert isinstance(results, list)
    assert len(results) >= 1
    assert "id" in results[0]
    assert "preview" in results[0]


@pytest.mark.asyncio
async def test_recent_limit_parameter(client: httpx.AsyncClient):
    for i in range(5):
        await client.post(
            "/ingest/thought",
            json={"content": f"Thought number {i} for testing the limit parameter in recent."},
        )
    r = await client.get("/recent", params={"limit": 3})
    assert r.status_code == 200
    assert len(r.json()) <= 3


# ── By date / since ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_by_date_valid(client: httpx.AsyncClient):
    r = await client.get("/by_date", params={"date": "2026-03-01"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_by_date_invalid_format(client: httpx.AsyncClient):
    r = await client.get("/by_date", params={"date": "not-a-date"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_since_returns_list(client: httpx.AsyncClient):
    await client.post(
        "/ingest/thought",
        json={"content": "Recent content to test the since endpoint retrieval."},
    )
    r = await client.get("/since", params={"hours": 1.0})
    assert r.status_code == 200
    results = r.json()
    assert isinstance(results, list)
    assert len(results) >= 1


# ── Digest ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_digest_structure(client: httpx.AsyncClient):
    await client.post(
        "/ingest/thought",
        json={"content": "Digest test content for today's activity summary."},
    )
    r = await client.get("/digest")
    assert r.status_code == 200
    data = r.json()
    assert "date" in data
    assert "total" in data
    assert "by_type" in data
    assert "samples" in data
    assert data["total"] >= 1
