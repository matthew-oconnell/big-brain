# big-brain

A federated personal knowledge system with semantic search. Store thoughts, terminal
history, chat logs, files, and anything else — then query it by meaning.

Inspired by Gevulot from *The Quantum Thief*: hierarchical encryption keys let you
share any subtree of your knowledge with other nodes or people, while keeping the
rest opaque.

## Architecture

- **Local-first**: fully offline, cloud sync is optional and async
- **Semantic search**: `nomic-embed-text` embeddings via `fastembed`, stored in LanceDB
- **Encrypted at rest**: AES-256-GCM blobs, HKDF key tree (coming in M5)
- **Federated**: multiple nodes (home, work, etc.) with configurable sharing policies
- **MCP server**: plug your brain into Claude and other MCP-aware tools (coming in M4)

## Milestones

| # | Name | Status |
|---|------|--------|
| M0 | Core pipeline — embed, store, search | 🚧 In progress |
| M1 | Daemon + shell hook — terminal history | ⬜ Planned |
| M2 | Chat importers — Claude, VSCode | ⬜ Planned |
| M3 | Web UI — search + capture in browser | ⬜ Planned |
| M4 | MCP server — query from Claude | ⬜ Planned |
| M5 | Encryption — key tree, blobs | ⬜ Planned |
| M6 | Cloud sync — provider-agnostic blobs | ⬜ Planned |
| M7 | Federation — node-to-node sharing | ⬜ Planned |
| M8 | Work node — no Docker, no cloud | ⬜ Planned |

## Quick Start

```bash
pip install -e ".[dev]"

# Add a thought
bb add "that thing I was trying to remember"

# Import a file
bb import path/to/notes.md

# Search
bb search "encryption key hierarchy"

# Start the daemon (for terminal history capture)
bb daemon start
```

## Shell Hook (terminal history)

Add to your `.bashrc` or `.zshrc`:

```bash
source "$(bb shell-hook-path)"
```

## Configuration

Config lives at `~/.config/bigbrain/config.toml`. Generated on first run.

## Data

All data stored locally at `~/.local/share/bigbrain/` by default.
