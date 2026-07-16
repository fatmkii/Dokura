from __future__ import annotations

import secrets
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from dokura.metadata.database import WriteScheduler
from dokura.metadata.models import File, Task
from dokura.metadata.tasks import ACTIVE_TASK_STATUSES


@dataclass(frozen=True, slots=True)
class CleanupPreview:
    confirmation_id: str
    file_count: int
    cache_file_count: int
    estimated_bytes: int


@dataclass(frozen=True, slots=True)
class _CleanupCandidates:
    file_ids: frozenset[str]
    cache_paths: frozenset[Path]


class CacheCleanupManager:
    """Previews and revalidates the server-side recovery scope before deletion."""

    def __init__(
        self, engine: Engine, writer: WriteScheduler, metadata_dir: Path,
        content_dir: Path | None = None,
    ) -> None:
        self.engine = engine
        self.writer = writer
        self.metadata_dir = metadata_dir
        self.cover_dir = metadata_dir / "covers"
        self.content_dir = content_dir
        self._confirmations: dict[str, _CleanupCandidates] = {}
        self._lock = Lock()

    def _metadata_path(self, relative_path: str) -> Path | None:
        candidate = (self.metadata_dir / relative_path).resolve()
        metadata_root = self.metadata_dir.resolve()
        return candidate if candidate.is_relative_to(metadata_root) else None

    def preview(self) -> CleanupPreview:
        with self._lock, Session(self.engine) as session:
            deleted_ids = set(session.scalars(
                select(File.id).where(File.present.is_(False), File.storage_unavailable.is_(False))
            ))
            referenced = {
                str(candidate)
                for path in session.scalars(select(File.cover_path).where(File.cover_path.is_not(None)))
                if (candidate := self._metadata_path(path)) is not None
            }
            candidates = self._filesystem_candidates(referenced)
            for record in session.scalars(select(File).where(File.id.in_(deleted_ids))):
                if record.cover_path:
                    if cover := self._metadata_path(record.cover_path):
                        candidates.add(cover)
            token = secrets.token_urlsafe(24)
            self._confirmations[token] = _CleanupCandidates(
                frozenset(deleted_ids), frozenset(candidates)
            )
            return CleanupPreview(
                token,
                len(deleted_ids),
                len(candidates),
                sum(self._size(path) for path in candidates),
            )

    def execute(self, confirmation_id: str) -> dict[str, int]:
        with self._lock:
            plan = self._confirmations.pop(confirmation_id, None)
            if plan is None:
                raise ValueError("cleanup_confirmation_invalid")

            released = 0
            succeeded = 0
            busy = 0
            failed = 0
            with Session(self.engine) as session:
                active = set(session.scalars(
                    select(Task.file_id).where(
                        Task.file_id.in_(plan.file_ids), Task.status.in_(ACTIVE_TASK_STATUSES)
                    )
                ))
                records = session.scalars(
                    select(File).where(
                        File.id.in_(plan.file_ids), File.present.is_(False),
                        File.storage_unavailable.is_(False),
                    )
                ).all()
            for record in records:
                if record.id in active:
                    busy += 1
                    continue
                if self.content_dir is not None:
                    try:
                        if stat.S_ISREG((self.content_dir / record.relative_path).lstat().st_mode):
                            busy += 1
                            continue
                    except FileNotFoundError:
                        pass
                    except OSError:
                        busy += 1
                        continue
                cover = self._metadata_path(record.cover_path) if record.cover_path else None
                try:
                    if cover is not None and cover.is_file():
                        size = cover.stat().st_size
                        cover.unlink()
                        released += size
                    with self.writer.transaction() as session:
                        current = session.get(File, record.id)
                        if current is not None and not current.present and not current.storage_unavailable:
                            session.delete(current)
                    succeeded += 1
                except OSError:
                    failed += 1

            with Session(self.engine) as session:
                referenced = {
                    str(candidate)
                    for path in session.scalars(select(File.cover_path).where(File.cover_path.is_not(None)))
                    if (candidate := self._metadata_path(path)) is not None
                }
            still_invalid = self._filesystem_candidates(referenced)
            for path in plan.cache_paths & still_invalid:
                if not path.exists():
                    continue
                try:
                    size = self._size(path)
                    path.unlink()
                    released += size
                    succeeded += 1
                except OSError:
                    failed += 1
            return {
                "released_bytes": released,
                "success_count": succeeded,
                "busy_skipped_count": busy,
                "failure_count": failed,
            }

    def _filesystem_candidates(self, referenced: set[str]) -> set[Path]:
        result: set[Path] = set()
        if not self.cover_dir.is_dir():
            return result
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        for path in self.cover_dir.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            except OSError:
                continue
            if path.name.endswith(".tmp"):
                if modified < cutoff:
                    result.add(path.resolve())
            elif str(path.resolve()) not in referenced:
                result.add(path.resolve())
        return result

    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0
