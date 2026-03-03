"""Configuration — loaded from ~/.config/bigbrain/config.toml on startup."""

import socket
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class StorageConfig(BaseModel):
    data_dir: Path = Path.home() / ".local" / "share" / "bigbrain"
    blob_provider: Literal["local", "s3", "r2", "b2"] = "local"
    # Provider-specific options live under [storage.blob.*] in the toml


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "ollama", "noop"] = "noop"
    # Anthropic default: cheapest model, fast enough for background tagging
    # Ollama default: Qwen3 MoE — 30B capacity, ~3B inference cost
    model: str = "claude-haiku-4-5-20251001"
    ollama_model: str = "alibayram/Qwen3-30B-A3B-Instruct-2507:latest"
    base_url: str | None = None  # for ollama, defaults to http://localhost:11434


class DaemonConfig(BaseModel):
    port: int = 7777
    host: str = "127.0.0.1"


class Settings(BaseSettings):
    node_id: str = socket.gethostname()
    node_name: str = socket.gethostname()

    storage: StorageConfig = StorageConfig()
    llm: LLMConfig = LLMConfig()
    daemon: DaemonConfig = DaemonConfig()

    # Directories to watch for automatic file ingestion
    watch_dirs: list[Path] = Field(default_factory=list)

    # Key paths that should never leave this node (federation policy)
    private_key_paths: list[str] = Field(default_factory=lambda: ["work"])

    class Config:
        env_prefix = "BB_"

    @classmethod
    def load(cls) -> "Settings":
        config_path = Path.home() / ".config" / "bigbrain" / "config.toml"
        if config_path.exists():
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
            return cls.model_validate(data)
        return cls()

    def ensure_dirs(self) -> None:
        self.storage.data_dir.mkdir(parents=True, exist_ok=True)
        (self.storage.data_dir / "blobs").mkdir(exist_ok=True)
        (self.storage.data_dir / "vectors").mkdir(exist_ok=True)


