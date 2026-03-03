"""SQLite metadata store — full chunk content and sync state."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlmodel import Field, Session, SQLModel, create_engine, select


class ChunkRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    content: str
    content_type: str
    source_node: str
    origin_path: str | None = None
    timestamp: datetime
    tags: str = "[]"             # JSON-encoded list
    activity_summary: str | None = None
    activity_tags: str = "[]"    # JSON-encoded list
    exit_code: int | None = None
    working_directory: str | None = None
    key_path: str = "personal"
    content_hash: str = ""
    synced_at: datetime | None = None
    context_estimated_at: datetime | None = None


class MetaStore:
    def __init__(self, data_dir: Path) -> None:
        db_path = data_dir / "meta.db"
        self._engine = create_engine(f"sqlite:///{db_path}")
        SQLModel.metadata.create_all(self._engine)

    def save(self, chunk: "Chunk") -> None:  # type: ignore[name-defined]
        import json
        from bb.core.chunk import Chunk
        record = ChunkRecord(
            id=str(chunk.id),
            content=chunk.content,
            content_type=chunk.content_type.value,
            source_node=chunk.source_node,
            origin_path=chunk.origin_path,
            timestamp=chunk.timestamp,
            tags=json.dumps(chunk.tags),
            activity_summary=chunk.activity_summary,
            activity_tags=json.dumps(chunk.activity_tags),
            exit_code=chunk.exit_code,
            working_directory=chunk.working_directory,
            key_path=chunk.key_path,
            content_hash=chunk.content_hash,
            synced_at=chunk.synced_at,
        )
        with Session(self._engine) as session:
            session.merge(record)
            session.commit()

    def get(self, chunk_id: str) -> ChunkRecord | None:
        with Session(self._engine) as session:
            return session.get(ChunkRecord, chunk_id)

    def update_context(
        self, chunk_id: str, summary: str, activity_tags: list[str]
    ) -> None:
        import json
        with Session(self._engine) as session:
            record = session.get(ChunkRecord, chunk_id)
            if record:
                record.activity_summary = summary
                record.activity_tags = json.dumps(activity_tags)
                record.context_estimated_at = datetime.now(timezone.utc)
                session.commit()

    def unsynced(self) -> list[ChunkRecord]:
        with Session(self._engine) as session:
            return list(session.exec(select(ChunkRecord).where(ChunkRecord.synced_at == None)).all())  # noqa: E711

    def mark_synced(self, chunk_id: str) -> None:
        with Session(self._engine) as session:
            record = session.get(ChunkRecord, chunk_id)
            if record:
                record.synced_at = datetime.now(timezone.utc)
                session.commit()

    def pending_context_estimation(self) -> list[ChunkRecord]:
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(ChunkRecord).where(ChunkRecord.context_estimated_at == None)  # noqa: E711
                ).all()
            )

    def today(self) -> list[ChunkRecord]:
        """Return all chunks created since midnight UTC today."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(ChunkRecord).where(ChunkRecord.timestamp >= today_start)
                    .order_by(ChunkRecord.timestamp.desc())  # type: ignore[arg-type]
                ).all()
            )

    def by_date(self, date: "date_type") -> list[ChunkRecord]:  # type: ignore[name-defined]
        """Return all chunks for a specific calendar date (naive comparison)."""
        from datetime import date as date_type, timedelta
        day_start = datetime(date.year, date.month, date.day)
        day_end = day_start + timedelta(days=1)
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(ChunkRecord)
                    .where(ChunkRecord.timestamp >= day_start)
                    .where(ChunkRecord.timestamp < day_end)
                    .order_by(ChunkRecord.timestamp.desc())  # type: ignore[arg-type]
                ).all()
            )

    def since(self, cutoff: datetime) -> list[ChunkRecord]:
        """Return all chunks at or after cutoff, most recent first."""
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(ChunkRecord)
                    .where(ChunkRecord.timestamp >= cutoff)
                    .order_by(ChunkRecord.timestamp.desc())  # type: ignore[arg-type]
                ).all()
            )
