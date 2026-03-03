"""BlobStore protocol — swap cloud providers with a config change."""

from typing import Protocol


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes) -> None:
        """Store bytes at key. Overwrites if exists."""
        ...

    async def get(self, key: str) -> bytes:
        """Retrieve bytes by key. Raises KeyError if not found."""
        ...

    async def delete(self, key: str) -> None:
        """Delete a key. No-op if not found."""
        ...

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all keys with the given prefix."""
        ...

    async def exists(self, key: str) -> bool:
        """Return True if the key exists."""
        ...
