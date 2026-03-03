"""Vector store backed by LanceDB — pure Python, no server needed."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import lancedb
import pyarrow as pa

if TYPE_CHECKING:
    from bb.core.chunk import Chunk

SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("content_type", pa.string()),
        pa.field("source_node", pa.string()),
        pa.field("timestamp", pa.string()),
        pa.field("key_path", pa.string()),
        pa.field("tags", pa.list_(pa.string())),
        pa.field("activity_tags", pa.list_(pa.string())),
        pa.field("activity_summary", pa.string()),
        pa.field("origin_path", pa.string()),
        pa.field("content_hash", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 768)),  # nomic-embed-text dims
    ]
)

TABLE_NAME = "chunks"


class VectorStore:
    def __init__(self, data_dir: Path) -> None:
        self._db = lancedb.connect(str(data_dir / "vectors"))
        self._table: lancedb.table.Table | None = None

    def _get_table(self) -> lancedb.table.Table:
        if self._table is None:
            if TABLE_NAME in self._db.table_names():
                self._table = self._db.open_table(TABLE_NAME)
            else:
                self._table = self._db.create_table(TABLE_NAME, schema=SCHEMA)
        return self._table

    def add(self, chunk: "Chunk", embedding: list[float]) -> None:
        row = {
            "id": str(chunk.id),
            "content_type": chunk.content_type.value,
            "source_node": chunk.source_node,
            "timestamp": chunk.timestamp.isoformat(),
            "key_path": chunk.key_path,
            "tags": chunk.tags,
            "activity_tags": chunk.activity_tags,
            "activity_summary": chunk.activity_summary or "",
            "origin_path": chunk.origin_path or "",
            "content_hash": chunk.content_hash,
            "vector": embedding,
        }
        self._get_table().add([row])

    def search(self, embedding: list[float], limit: int = 10) -> list[dict]:
        return (
            self._get_table()
            .search(embedding)
            .metric("cosine")
            .limit(limit)
            .to_list()
        )

    def search_with_filter(
        self,
        embedding: list[float],
        content_types: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        query = self._get_table().search(embedding).metric("cosine").limit(limit)
        if content_types:
            types_str = ", ".join(f"'{t}'" for t in content_types)
            query = query.where(f"content_type IN ({types_str})")
        return query.to_list()

    def hash_exists(self, content_hash: str) -> bool:
        results = (
            self._get_table()
            .search()
            .where(f"content_hash = '{content_hash}'")
            .limit(1)
            .to_list()
        )
        return len(results) > 0

    def recent(self, limit: int = 20) -> list[dict]:
        """Get recent entries ordered by timestamp (most recent first)."""
        table = self._get_table()
        try:
            # Use to_arrow() to convert to PyArrow table (doesn't require pandas)
            arrow_table = table.to_arrow()
            # Convert to list of dicts
            all_rows = arrow_table.to_pylist()
            # Sort by timestamp descending (most recent first)
            all_rows.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            return all_rows[:limit]
        except Exception:
            # If that fails, try using head() and limit locally
            try:
                all_rows = table.head(1000).to_pylist() if hasattr(table.head(1000), 'to_pylist') else []
                if all_rows:
                    all_rows.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
                    return all_rows[:limit]
            except Exception:
                pass
            return []
