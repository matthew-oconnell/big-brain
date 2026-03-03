"""bb — the big-brain command line interface."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="bb",
    help="big-brain: your queryable second brain",
    no_args_is_help=True,
)
console = Console()
err = Console(stderr=True)


def _pipeline():
    from bb.core.config import Settings
    from bb.ingest.pipeline import IngestPipeline
    settings = Settings.load()
    return IngestPipeline(settings)


# ── add ──────────────────────────────────────────────────────────────────────

@app.command()
def add(
    content: Annotated[str, typer.Argument(help="Text to store")],
    tag: Annotated[list[str], typer.Option("--tag", "-t", help="Tag (repeatable)")] = [],
    content_type: Annotated[str, typer.Option("--type", help="Content type")] = "thought",
    key_path: Annotated[str, typer.Option("--key-path", help="Encryption key path")] = "personal",
) -> None:
    """Add a thought or snippet to your brain."""
    from bb.core.chunk import Chunk, ContentType

    chunk = Chunk(
        content=content,
        content_type=ContentType(content_type),
        source_node=socket.gethostname(),
        tags=tag,
        key_path=key_path,
    )
    pipeline = _pipeline()
    ids = asyncio.run(pipeline.ingest(chunk))
    if ids:
        console.print(f"[green]Stored[/green] {ids[0][:8]}…")
    else:
        console.print("[yellow]Duplicate — already in brain[/yellow]")


# ── import ────────────────────────────────────────────────────────────────────

@app.command(name="import")
def import_cmd(
    paths: Annotated[list[Path], typer.Argument(help="Files or directories to import")],
    tag: Annotated[list[str], typer.Option("--tag", "-t", help="Tag (repeatable)")] = [],
    recursive: Annotated[bool, typer.Option("--recursive", "-r")] = False,
) -> None:
    """Import one or more files into your brain."""
    from bb.ingest.file import import_path

    pipeline = _pipeline()
    total = 0
    for path in paths:
        ids = asyncio.run(import_path(path, pipeline, tags=tag, recursive=recursive))
        total += len(ids)
        if ids:
            console.print(f"[green]{path.name}[/green] → {len(ids)} chunk(s)")
        else:
            console.print(f"[yellow]{path.name}[/yellow] — nothing new")
    console.print(f"\nTotal: [bold]{total}[/bold] chunk(s) stored")


# ── search ────────────────────────────────────────────────────────────────────

@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query (semantic)")],
    limit: Annotated[int, typer.Option("--limit", "-n")] = 10,
    type_filter: Annotated[list[str], typer.Option("--type", "-t", help="Filter by content type")] = [],
) -> None:
    """Search your brain by meaning."""
    pipeline = _pipeline()
    results = pipeline.search(query, limit=limit, content_types=type_filter or None)

    if not results:
        console.print("[yellow]No results found[/yellow]")
        return

    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Type", style="cyan", width=12)
    table.add_column("Date", style="dim", width=12)
    table.add_column("Summary / Content", ratio=1)
    table.add_column("Score", style="dim", width=6)

    for r in results:
        display = r.get("activity_summary") or r["content"][:120].replace("\n", " ")
        score = f"{1 - r.get('_distance', 0):.2f}"
        date = r["timestamp"][:10] if r.get("timestamp") else "—"
        table.add_row(r["content_type"], date, display, score)

    console.print(table)


# ── journal ───────────────────────────────────────────────────────────────────

@app.command()
def j(
    content: Annotated[str, typer.Argument(help="Journal entry")],
    tag: Annotated[list[str], typer.Option("--tag", "-t")] = [],
) -> None:
    """Quickly add a journal entry. Alias for: bb add --type journal"""
    from bb.core.chunk import Chunk, ContentType

    chunk = Chunk(
        content=content,
        content_type=ContentType.JOURNAL,
        source_node=socket.gethostname(),
        tags=tag,
        key_path="personal/journal",
    )
    pipeline = _pipeline()
    ids = asyncio.run(pipeline.ingest(chunk))
    if ids:
        console.print(f"[green]Journal entry saved[/green] {ids[0][:8]}…")
    else:
        console.print("[yellow]Duplicate[/yellow]")


# ── recent ────────────────────────────────────────────────────────────────────

@app.command()
def recent(
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
) -> None:
    """Show recently ingested chunks."""
    pipeline = _pipeline()
    results = pipeline._vector.recent(limit)

    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Type", style="cyan", width=12)
    table.add_column("Date", style="dim", width=20)
    table.add_column("Preview", ratio=1)

    for r in results:
        record = pipeline._meta.get(r["id"])
        preview = ""
        if record:
            preview = (record.activity_summary or record.content[:100]).replace("\n", " ")
        date = r.get("timestamp", "")[:19].replace("T", " ")
        table.add_row(r["content_type"], date, preview)

    console.print(table)


# ── llm ──────────────────────────────────────────────────────────────────────

llm_app = typer.Typer(name="llm", help="Manage and test LLM context estimation.")
app.add_typer(llm_app)


@llm_app.command("test")
def llm_test() -> None:
    """Verify the configured LLM backend can estimate context."""
    from bb.core.config import Settings
    from bb.llm.factory import get_llm_client

    settings = Settings.load()
    provider = settings.llm.provider
    console.print(f"Provider: [bold]{provider}[/bold]")

    if provider == "ollama":
        console.print(f"Model:    [bold]{settings.llm.ollama_model}[/bold]")
        console.print(f"Base URL: [bold]{settings.llm.base_url or 'http://localhost:11434'}[/bold]")
    elif provider == "anthropic":
        console.print(f"Model:    [bold]{settings.llm.model}[/bold]")

    if provider == "noop":
        console.print("[yellow]Provider is 'noop' — context estimation is disabled.[/yellow]")
        console.print("Set [bold]provider = 'ollama'[/bold] or [bold]'anthropic'[/bold] in ~/.config/bigbrain/config.toml")
        return

    sample = (
        "git commit -m 'fix HKDF key derivation for shared subtrees'\n"
        "cd ~/Projects/big-brain && python -m pytest tests/"
    )
    console.print(f"\nSample content:\n[dim]{sample}[/dim]\n")
    console.print("Calling LLM…")

    try:
        client = get_llm_client(settings)
        result = asyncio.run(client.estimate_context(sample, "terminal"))
        console.print(f"[green]Summary:[/green]     {result.summary}")
        console.print(f"[green]Activity tags:[/green] {', '.join(result.activity_tags)}")
    except Exception as e:
        err.print(f"[red]Failed:[/red] {e}")
        raise typer.Exit(1)


@llm_app.command("status")
def llm_status() -> None:
    """Show current LLM configuration."""
    from bb.core.config import Settings
    settings = Settings.load()
    cfg = settings.llm
    console.print(f"Provider:      [bold]{cfg.provider}[/bold]")
    console.print(f"Anthropic model: {cfg.model}")
    console.print(f"Ollama model:    {cfg.ollama_model}")
    console.print(f"Ollama base URL: {cfg.base_url or 'http://localhost:11434 (default)'}")


# ── daemon ────────────────────────────────────────────────────────────────────

@app.command()
def daemon(
    action: Annotated[str, typer.Argument(help="start | stop | status")] = "start",
) -> None:
    """Manage the bb daemon (required for terminal history capture)."""
    console.print(f"[yellow]Daemon management coming in M1[/yellow] (action: {action})")


# ── shell-hook-path ───────────────────────────────────────────────────────────

@app.command()
def shell_hook_path() -> None:
    """Print the path to the shell hook script for sourcing in .bashrc/.zshrc."""
    import importlib.resources
    console.print("[yellow]Shell hook coming in M1[/yellow]")


if __name__ == "__main__":
    app()
