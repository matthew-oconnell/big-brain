"""bb — the big-brain command line interface."""

from __future__ import annotations

import asyncio
import socket
import sys
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


def _settings():
    from bb.core.config import Settings
    return Settings.load()


def _pipeline():
    from bb.ingest.pipeline import IngestPipeline
    return IngestPipeline(_settings())


# ── add ──────────────────────────────────────────────────────────────────────

@app.command()
def add(
    content: Annotated[str, typer.Argument(help="Text to store")],
    tag: Annotated[list[str], typer.Option("--tag", "-t", help="Tag (repeatable)")] = [],
    content_type: Annotated[str, typer.Option("--type", help="Content type")] = "thought",
    key_path: Annotated[str, typer.Option("--key-path")] = "personal",
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
    ids = asyncio.run(_pipeline().ingest(chunk))
    if ids:
        console.print(f"[green]Stored[/green] {ids[0][:8]}…")
    else:
        console.print("[yellow]Duplicate — already in brain[/yellow]")


# ── journal shortcut ──────────────────────────────────────────────────────────

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
    ids = asyncio.run(_pipeline().ingest(chunk))
    if ids:
        console.print("[green]Journal entry saved[/green]")
    else:
        console.print("[yellow]Duplicate[/yellow]")


# ── import ────────────────────────────────────────────────────────────────────

@app.command(name="import")
def import_cmd(
    paths: Annotated[list[Path], typer.Argument(help="Files or directories to import")],
    tag: Annotated[list[str], typer.Option("--tag", "-t")] = [],
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
    query: Annotated[str, typer.Argument(help="Semantic search query")],
    limit: Annotated[int, typer.Option("--limit", "-n")] = 10,
    type_filter: Annotated[list[str], typer.Option("--type", "-t")] = [],
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
        date = r.get("timestamp", "")[:10]
        table.add_row(r["content_type"], date, display, score)

    console.print(table)


# ── recent ────────────────────────────────────────────────────────────────────

@app.command()
def recent(limit: Annotated[int, typer.Option("--limit", "-n")] = 20) -> None:
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


# ── digest ────────────────────────────────────────────────────────────────────

@app.command()
def digest() -> None:
    """Show a summary of what was captured today."""
    from collections import Counter

    pipeline = _pipeline()
    today_records = pipeline._meta.today()

    if not today_records:
        console.print("[dim]Nothing captured today yet.[/dim]")
        return

    counts = Counter(r.content_type for r in today_records)
    console.print(f"\n[bold]Today's capture[/bold] — {len(today_records)} total\n")

    for content_type, count in counts.most_common():
        console.print(f"  [cyan]{content_type:<16}[/cyan] {count}")

    console.print("\n[bold]Recent samples:[/bold]")
    for record in today_records[:8]:
        preview = (record.activity_summary or record.content[:80]).replace("\n", " ")
        time_str = record.timestamp.strftime("%H:%M")
        console.print(f"  [dim]{time_str}[/dim]  [cyan]{record.content_type:<12}[/cyan]  {preview}")


# ── daemon ────────────────────────────────────────────────────────────────────

daemon_app = typer.Typer(name="daemon", help="Manage the bb background daemon.")
app.add_typer(daemon_app)


def _pid_path() -> Path:
    return _settings().storage.data_dir / "daemon.pid"


def _log_path() -> Path:
    return _settings().storage.data_dir / "daemon.log"


def _read_pid() -> int | None:
    pid_file = _pid_path()
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def _is_running(pid: int) -> bool:
    import os
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


@daemon_app.command("start")
def daemon_start(
    port: Annotated[int, typer.Option("--port", "-p")] = 7777,
) -> None:
    """Start the daemon in the background."""
    import os
    import subprocess

    pid = _read_pid()
    if pid and _is_running(pid):
        console.print(f"[yellow]Daemon already running[/yellow] (PID {pid})")
        return

    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [sys.executable, "-m", "bb.api.daemon"],
        start_new_session=True,
        stdout=open(log, "a"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "BB_DAEMON_PORT": str(port)},
    )
    _pid_path().write_text(str(proc.pid))
    console.print(f"[green]Daemon started[/green] (PID {proc.pid}, port {port})")
    console.print(f"Logs: {log}")


@daemon_app.command("stop")
def daemon_stop() -> None:
    """Stop the running daemon."""
    import os
    import signal

    pid = _read_pid()
    if not pid or not _is_running(pid):
        console.print("[yellow]Daemon is not running[/yellow]")
        _pid_path().unlink(missing_ok=True)
        return

    os.kill(pid, signal.SIGTERM)
    _pid_path().unlink(missing_ok=True)
    console.print(f"[green]Daemon stopped[/green] (PID {pid})")


@daemon_app.command("status")
def daemon_status() -> None:
    """Show daemon status and recent log lines."""
    pid = _read_pid()
    if pid and _is_running(pid):
        console.print(f"[green]Running[/green] (PID {pid})")
    else:
        console.print("[red]Not running[/red]")
        _pid_path().unlink(missing_ok=True)

    log = _log_path()
    if log.exists():
        lines = log.read_text().splitlines()[-10:]
        if lines:
            console.print("\n[dim]Last 10 log lines:[/dim]")
            for line in lines:
                console.print(f"  [dim]{line}[/dim]")


@daemon_app.command("logs")
def daemon_logs(
    lines: Annotated[int, typer.Option("--lines", "-n")] = 50,
    follow: Annotated[bool, typer.Option("--follow", "-f")] = False,
) -> None:
    """Show daemon logs."""
    import subprocess
    log = _log_path()
    if not log.exists():
        console.print("[yellow]No log file found[/yellow]")
        return
    args = ["tail", f"-n{lines}"]
    if follow:
        args.append("-f")
    args.append(str(log))
    subprocess.run(args)


# ── shell hook path ───────────────────────────────────────────────────────────

@app.command()
def shell_hook_path(
    shell: Annotated[str, typer.Argument(help="bash or zsh")] = "bash",
) -> None:
    """Print the shell hook path. Source it in your .bashrc or .zshrc."""
    import importlib.resources
    valid = {"bash", "zsh"}
    if shell not in valid:
        err.print(f"[red]Unknown shell '{shell}'. Choose: {', '.join(valid)}[/red]")
        raise typer.Exit(1)
    hook = importlib.resources.files("bb.shell") / f"hook.{shell}"
    console.print(str(hook))


# ── llm ──────────────────────────────────────────────────────────────────────

llm_app = typer.Typer(name="llm", help="Manage and test LLM context estimation.")
app.add_typer(llm_app)


@llm_app.command("test")
def llm_test() -> None:
    """Verify the configured LLM backend can estimate context."""
    from bb.llm.factory import get_llm_client

    settings = _settings()
    provider = settings.llm.provider
    console.print(f"Provider: [bold]{provider}[/bold]")

    if provider == "ollama":
        console.print(f"Model:    [bold]{settings.llm.ollama_model}[/bold]")
        console.print(f"Base URL: [bold]{settings.llm.base_url or 'http://localhost:11434'}[/bold]")
    elif provider == "anthropic":
        console.print(f"Model:    [bold]{settings.llm.model}[/bold]")

    if provider == "noop":
        console.print("[yellow]Provider is 'noop' — context estimation is disabled.[/yellow]")
        console.print("Set provider = 'ollama' or 'anthropic' in ~/.config/bigbrain/config.toml")
        return

    sample = (
        "git commit -m 'fix HKDF key derivation for shared subtrees'\n"
        "cd ~/Projects/big-brain && python -m pytest tests/"
    )
    console.print(f"\nSample:\n[dim]{sample}[/dim]\n")
    console.print("Calling LLM…")

    try:
        client = get_llm_client(settings)
        result = asyncio.run(client.estimate_context(sample, "terminal"))
        console.print(f"[green]Summary:[/green]       {result.summary}")
        console.print(f"[green]Activity tags:[/green] {', '.join(result.activity_tags)}")
    except Exception as e:
        err.print(f"[red]Failed:[/red] {e}")
        raise typer.Exit(1)


@llm_app.command("status")
def llm_status() -> None:
    """Show current LLM configuration."""
    cfg = _settings().llm
    console.print(f"Provider:        [bold]{cfg.provider}[/bold]")
    console.print(f"Anthropic model: {cfg.model}")
    console.print(f"Ollama model:    {cfg.ollama_model}")
    console.print(f"Ollama base URL: {cfg.base_url or 'http://localhost:11434 (default)'}")


if __name__ == "__main__":
    app()
