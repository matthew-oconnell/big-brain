"""Filesystem BlobStore — the default for offline/dev use and work nodes."""

from pathlib import Path


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Use first 2 chars of key as a subdirectory to avoid huge flat dirs
        return self._root / key[:2] / key

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise KeyError(key)
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    async def list_keys(self, prefix: str = "") -> list[str]:
        keys = []
        for p in self._root.rglob("*"):
            if p.is_file():
                key = p.name
                if key.startswith(prefix):
                    keys.append(key)
        return keys

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()
