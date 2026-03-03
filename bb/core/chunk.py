"""Core data model. A Chunk is the atomic unit of the knowledge store."""

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ContentType(StrEnum):
    TERMINAL = "terminal"
    THOUGHT = "thought"
    JOURNAL = "journal"
    FILE = "file"
    CHAT_CLAUDE = "chat_claude"
    CHAT_VSCODE = "chat_vscode"
    EMAIL = "email"
    NOTE = "note"
    IMAGE = "image"


class Chunk(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    content: str

    content_type: ContentType
    source_node: str  # hostname of the machine that created this
    origin_path: str | None = None  # file path, URL, or source identifier

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # User-provided or importer-provided tags
    tags: list[str] = Field(default_factory=list)

    # LLM-generated context (populated asynchronously after ingest)
    activity_summary: str | None = None
    activity_tags: list[str] = Field(default_factory=list)

    # Terminal-specific fields
    exit_code: int | None = None
    working_directory: str | None = None

    # Encryption key path (e.g. "personal/journal") — used in M5
    key_path: str = "personal"

    # Sync state
    synced_at: datetime | None = None

    @property
    def content_hash(self) -> str:
        """SHA-256 of content for deduplication."""
        import hashlib
        return hashlib.sha256(self.content.encode()).hexdigest()

    def is_terminal_noise(self) -> bool:
        """True for commands unlikely to be worth storing."""
        noisy = {"ls", "ll", "la", "cd", "pwd", "clear", "exit", "history"}
        cmd = self.content.strip().split()[0] if self.content.strip() else ""
        return cmd in noisy
