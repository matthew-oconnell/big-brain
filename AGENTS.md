# AGENTS.md — Guide for AI Coding Assistants

This file tells AI agents how to work safely and consistently on this codebase.
Read it fully before making changes. Update it when you add new patterns.

---

## What This Project Is

A federated personal knowledge system ("second brain") with semantic search.
Inspired by Gevulot from *The Quantum Thief* — hierarchical encryption keys let
you share any subtree of your knowledge while keeping the rest opaque.

**Owner:** Research scientist (CFD). High-value data includes terminal history,
CFD input files (JSON), Claude/VSCode chat logs, journal entries.

---

## Architecture Invariants — Never Violate These

1. **All ingest goes through `IngestPipeline`** (`bb/ingest/pipeline.py`).
   Never write directly to vector/meta/blob stores from importers or the daemon.

2. **Chunks are immutable once stored.** The system is append-only.
   Never update a chunk's content — create a new one instead.

3. **Vector embeddings are never encrypted.** They are just floating-point numbers.
   Only the content blob (stored separately) is encrypted (M5+).

4. **The shell hook must never block the terminal prompt.**
   `bb/shell/capture.py` uses stdlib only (no bb imports) and has a 1-second timeout.
   Do not add heavy imports or network calls that could hang.

5. **`BlobStore` protocol is the only way to talk to cloud storage.**
   (`bb/storage/blob/base.py`). New cloud providers implement this protocol.
   Never import boto3/cloudflare/etc. outside of `bb/storage/blob/`.

6. **`LLMClient` protocol is the only way to call LLMs.**
   (`bb/llm/base.py`). New LLM backends implement this protocol.
   Never import `anthropic`/`httpx`-to-ollama outside of `bb/llm/`.

7. **Work-tagged data never leaves the work node.**
   Anything with `key_path` starting with `"work"` is governed by
   `private_key_paths` in config. Federation (M7) must honour this.

8. **Never log chunk content.** Only log IDs, types, and hashes.
   Chunk content may be sensitive. `logger.info("Stored %s [%s]", chunk.id, chunk.content_type)` is correct. `logger.info(chunk.content)` is not.

---

## Key Files and What They Own

| File | Owns |
|---|---|
| `bb/core/chunk.py` | `Chunk` model, `ContentType` enum. Changes here ripple everywhere. |
| `bb/core/config.py` | `Settings`, `LLMConfig`, `StorageConfig`. Add new config fields here. |
| `bb/core/embedder.py` | Embedding model (nomic-embed-text via fastembed). One model, cached. |
| `bb/ingest/pipeline.py` | The single ingest path: dedup → chunk → embed → store → queue context. |
| `bb/ingest/chunker.py` | Text splitting. Paragraph-aware with overlap. |
| `bb/storage/vector.py` | LanceDB wrapper. Schema defined here — changes need migration thought. |
| `bb/storage/meta.py` | SQLite via SQLModel. `ChunkRecord` mirrors `Chunk`. |
| `bb/storage/blob/base.py` | `BlobStore` Protocol. All cloud backends implement this. |
| `bb/llm/base.py` | `LLMClient` Protocol + `ContextEstimate` model. |
| `bb/llm/factory.py` | Reads `settings.llm.provider`, returns the right `LLMClient`. |
| `bb/api/daemon.py` | FastAPI daemon on port 7777. All ingest/search HTTP endpoints. |
| `bb/shell/capture.py` | Stdlib-only terminal capture. Must stay minimal and fast. |
| `bb/cli/main.py` | All user-facing commands. Sub-apps: `daemon_app`, `llm_app`. |

---

## How to Add a New Content Type

1. Add the value to `ContentType` in `bb/core/chunk.py`
2. Add an importer in `bb/ingest/` (see `bb/ingest/file.py` as a template)
3. Add a daemon endpoint in `bb/api/daemon.py` if it needs an HTTP ingest path
4. Add a CLI command in `bb/cli/main.py` if the user needs to trigger it manually
5. Update `ContentType` doc comment in `bb/core/chunk.py`
6. Update the milestone table in `README.md` if this is M2+ work

## How to Add a New LLM Backend

1. Create `bb/llm/<name>_llm.py` implementing the `LLMClient` protocol
2. Add `"<name>"` to the `Literal` in `LLMConfig.provider` in `bb/core/config.py`
3. Add the branch to `get_llm_client()` in `bb/llm/factory.py`
4. Add config fields (model name, base URL, etc.) to `LLMConfig` in `bb/core/config.py`
5. Document in `config.example.toml`
6. Update `bb llm status` in `bb/cli/main.py` to show the new fields

## How to Add a New Cloud Storage Backend

1. Create `bb/storage/blob/<name>.py` implementing the `BlobStore` protocol
2. Add `"<name>"` to the `Literal` in `StorageConfig.blob_provider`
3. Add a factory/instantiation path (currently done in `IngestPipeline.__init__` — extract to a factory when there are 3+ providers)
4. Document required env vars / config fields in `config.example.toml`

---

## Milestone Status

| # | Name | Status | Key Files |
|---|------|--------|-----------|
| M0 | Core pipeline — embed, store, search | ✅ Done | `core/`, `storage/`, `ingest/pipeline.py` |
| M1 | Daemon + shell hook + file watcher | ✅ Done | `api/daemon.py`, `shell/`, `ingest/watcher.py` |
| M2 | Chat importers — Claude Code, VSCode | ✅ Done | `ingest/chat/` |
| M3 | Web UI — search + capture in browser | ✅ Done | `bb/web/` |
| M4 | MCP server — query from Claude | ✅ Done | `bb/api/mcp.py` |
| M5 | Encryption — Argon2 + HKDF key tree | ⬜ Planned | `bb/core/crypto.py` (create) |
| M6 | Cloud sync — provider-agnostic blobs | ⬜ Planned | `bb/sync/` (create), `bb/storage/blob/<provider>.py` |
| M7 | Federation — node-to-node sharing | ⬜ Planned | `bb/sync/federation.py` (create) |
| M8 | Work node — no Docker, no cloud | ⬜ Planned | config-level, same codebase |

**When you complete a milestone, update the table above and the table in `README.md`.**

---

## M2 Chat Importers — What to Build Next

Importers live in `bb/ingest/chat/`. Each is a module with an `import_<source>()` function.

**Claude Code** (`bb/ingest/chat/claude_code.py`):
- Walk `~/.claude/` and `.claude/` directories in configured project dirs
- Parse conversation JSON files (format: investigate at runtime)
- Use `ContentType.CHAT_CLAUDE`

**VSCode** (`bb/ingest/chat/vscode.py`):
- Look in `~/.config/Code/User/workspaceStorage/` for Copilot/Continue chat DBs
- May be SQLite — use `sqlite3` stdlib
- Use `ContentType.CHAT_VSCODE`

**Generic** (`bb/ingest/chat/generic.py`):
- Accept markdown files, plain text exports, JSON with configurable field mapping
- `bb import --type chat_claude path/to/export.md`

All importers must:
- Be idempotent (safe to run multiple times — dedup handles it)
- Support `--since DATE` to skip old entries
- Pass through `IngestPipeline.ingest()` — no direct storage access

---

## M4 MCP Server — Design Notes

The MCP server wraps the daemon. It does not have its own data layer.

Tools to expose:
- `search_brain(query, limit, content_types)` → ranked results
- `add_thought(content, tags)` → ingest
- `get_recent_context(hours)` → what has been captured recently
- `get_by_date(date)` → retrieve a day's activity

Implementation: use the `mcp` Python library from Anthropic.
Register in `~/.claude/mcp.json` (Claude Code) or equivalent.
File: `bb/api/mcp.py`

---

## M5 Encryption — Design Notes

Key hierarchy: `master_key = Argon2(passphrase)`, then `HKDF(parent, label)` for each level.

```
master  →  personal/  →  journal/  →  2024-q1/
        →  work/      →  terminal/
                      →  projects/  →  project-alpha/
```

Share token = derived key at a given path level. Recipient can decrypt everything below it.

- Encrypt: `AES-256-GCM`. Store nonce alongside encrypted blob.
- Vectors stay plaintext (needed for search, not human-readable).
- `key_path` field on `Chunk` determines which derived key to use.
- Key material never stored — derived fresh from passphrase each session.
- File: `bb/core/crypto.py`
- Migration: `bb rekey` command encrypts existing unencrypted blobs.

---

## Privacy Rules (non-negotiable)

- Shell hook is fire-and-forget with a 1-second timeout. A hanging daemon must not freeze the terminal.
- Daemon logs show chunk IDs and types only, never content.
- `key_path` values starting with `"work"` are governed by `private_key_paths` — they cannot appear in cloud sync (M6) or federation responses (M7) without explicit configuration.
- Embedding model runs locally (fastembed). Do not add a cloud embedding option without an explicit user request and a config guard.

---

## Code Conventions

- **Python 3.11+**, `from __future__ import annotations` in all files.
- **Pydantic v2** for all models. Use `model_copy(update={...})` not `copy(update={...})`.
- **Async throughout** the ingest/storage layer. CLI uses `asyncio.run()` at the boundary.
- **Protocol-based extensibility** — prefer `typing.Protocol` over ABC for the plugin points.
- **No heavy imports at module level in `bb/shell/capture.py`** — stdlib only.
- **Type hints everywhere.** `mypy --strict` is the target (not enforced yet, but aim for it).
- **Ruff** for linting. Config in `pyproject.toml`.

---

## Running Tests

```bash
# Install dev dependencies first (only needed once)
~/.local/share/bigbrain/venv/bin/pip install -e ".[dev]"

# Run all tests
pytest tests/

# Common flags
pytest tests/ -x          # stop on first failure
pytest tests/ -v          # verbose output
pytest tests/ -k chunker  # run tests matching a keyword
pytest tests/ --tb=short  # shorter tracebacks

# Run a specific file
pytest tests/test_chunker.py
pytest tests/test_api.py -v
```

### Test files and what they cover

| File | What it tests |
|---|---|
| `tests/test_pipeline.py` | Core ingest pipeline: ingest+search, dedup, noise filtering, chunking |
| `tests/test_chunker.py` | `chunk_text()` and `_split_sentences()`: empty input, short text, paragraph splits, sentence splits with overlap |
| `tests/test_storage.py` | `LocalBlobStore`: put/get/delete/exists/list; `MetaStore`: save/get/update_context/by_date/since/today |
| `tests/test_chat_importers.py` | `_parse_text_content()`, `_iter_messages()`, `import_claude_code()`, VSCode helpers, `import_vscode()` — with synthetic fixture data |
| `tests/test_file_ingest.py` | `is_text_file()`, `is_image_file()`, `import_file()`: text, empty, unsupported type, missing file, origin_path override, tags |
| `tests/test_api.py` | FastAPI endpoints: `/health`, `/ingest/thought`, `/ingest/terminal`, `/search`, `/recent`, `/by_date`, `/since`, `/digest` |
| `tests/test_mcp_tools.py` | MCP tool functions: `search_brain`, `add_thought`, `get_recent_context`, `get_by_date`, `get_stats` — with mocked `_get`/`_post` |

### Test conventions

- All tests use `tmp_path` (pytest fixture) for storage — never touch real user data.
- `tests/conftest.py` provides shared `pipeline`, `settings`, `make_chunk()` helpers.
- Async tests use `@pytest.mark.asyncio` (configured globally via `asyncio_mode = "auto"` in `pyproject.toml`).
- API tests bypass the lifespan by injecting `_pipeline` directly into `bb.api.daemon`.
- MCP tool tests mock `bb.api.mcp._get` and `bb.api.mcp._post` — no daemon required.
- Image import tests expect `RuntimeError` when Ollama is not running (correct behaviour).

### Adding tests for new features

1. **New importer**: add `test_import_<name>_basic()` and `test_import_<name>_idempotent()` in `tests/test_chat_importers.py` or a new file.
2. **New API endpoint**: add it to `tests/test_api.py`. Use the `client` fixture which injects a real pipeline.
3. **New MCP tool**: add unit tests in `tests/test_mcp_tools.py` with mocked `_get`/`_post`.
4. **New storage method**: add it to `tests/test_storage.py`.
5. **New content type or detection logic**: add it to `tests/test_file_ingest.py`.

---

## Install Script

`install.sh` — idempotent, safe to re-run.
If you add new config fields, update `config.example.toml`.
If you add new shell-level integrations, update `install.sh`.

---

## Updating This File

Update `AGENTS.md` when:
- A milestone is completed (update the status table)
- A new extension point is added (new protocol, new factory branch)
- A new privacy or architecture invariant is established
- The M2+ design notes become stale relative to what was actually built
