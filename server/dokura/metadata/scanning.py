from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from dokura.metadata.analysis_service import FileSnapshot
from dokura.metadata.database import WriteScheduler
from dokura.metadata.filename_parser import PARSER_VERSION, parse_filename
from dokura.metadata.models import AnalysisStatus, CoverStatus, Directory, File, Scan, Task, utc_now
from dokura.metadata.natural_sort import natural_sort_bytes, normalized_casefold
from dokura.metadata.repository import _apply_identity_and_parse, _replace_tags
from dokura.metadata.tasks import ACTIVE_TASK_STATUSES, ForegroundPressure, TaskScheduler


logger = logging.getLogger(__name__)
BATCH_SIZE = 200


def _cover_is_missing(cover_root: Path, relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "covers":
        return True
    return not (cover_root.parent / path).is_file()


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    relative_path: str
    snapshot: FileSnapshot


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    scan_id: str
    status: str
    checked_entries: int
    changes_found: int
    successful_directories: int
    failed_directories: int
    errors: tuple[dict[str, str], ...]


class ScanCoordinator:
    """Serializes scans and collapses all in-flight repeat requests to one follow-up."""

    def __init__(
        self,
        engine: Engine,
        writer: WriteScheduler,
        content_dir: Path,
        tasks: TaskScheduler,
        pressure: ForegroundPressure,
    ) -> None:
        self.engine = engine
        self.writer = writer
        self.content_dir = content_dir
        self.tasks = tasks
        self.pressure = pressure
        self._requested = asyncio.Event()
        self._running = False
        self._follow_up = False
        self._stopped = False
        self._warned_symlinks: set[str] = set()

    @property
    def running(self) -> bool:
        return self._running

    def request_scan(self) -> bool:
        if self._running:
            was_new = not self._follow_up
            self._follow_up = True
            return was_new
        was_new = not self._requested.is_set()
        self._requested.set()
        return was_new

    async def run(self) -> None:
        self.request_scan()
        while not self._stopped:
            await self._requested.wait()
            self._requested.clear()
            self._running = True
            try:
                await asyncio.to_thread(self.scan_once)
            finally:
                self._running = False
            self.tasks.wake()
            if self._follow_up:
                self._follow_up = False
                self._requested.set()

    async def stop(self) -> None:
        self._stopped = True
        self._requested.set()

    def scan_once(self) -> ScanOutcome:
        scan_id = str(uuid.uuid4())
        started = utc_now()
        with self.writer.transaction() as session:
            session.add(Scan(id=scan_id, status="running", started_at=started))

        checked = 0
        changes = 0
        successful_dirs: set[str] = set()
        failed_dirs: dict[str, str] = {}
        batch: list[DiscoveredFile] = []

        try:
            iterator = self._walk(successful_dirs, failed_dirs)
            for item, entry_count in iterator:
                checked += entry_count
                if item is None:
                    continue
                batch.append(item)
                if len(batch) == BATCH_SIZE:
                    changes += self._reconcile_batch(batch, scan_id)
                    batch.clear()
                    self.pressure.wait_background()
            if batch:
                changes += self._reconcile_batch(batch, scan_id)
                self.pressure.wait_background()
            root_failed = "" in failed_dirs
            changes += self._reconcile_missing(scan_id, failed_dirs, root_failed)
            changes += self._reconcile_directories(successful_dirs, failed_dirs, root_failed)
            status = "failed" if root_failed else ("partial" if failed_dirs else "completed")
        except Exception as exc:
            logger.exception("扫描 Content 失败", extra={"scan_id": scan_id})
            failed_dirs.setdefault("", type(exc).__name__)
            status = "failed"

        completed = utc_now()
        result = {
            "successful_directories": len(successful_dirs),
            "failed_directories": len(failed_dirs),
            "errors": [{"path": path, "reason": reason} for path, reason in failed_dirs.items()],
        }
        with self.writer.transaction() as session:
            scan = session.get(Scan, scan_id)
            if scan is not None:
                scan.status = status
                scan.completed_at = completed
                scan.checked_entries = checked
                scan.changes_found = changes
                scan.result_json = json.dumps(result, ensure_ascii=False)
        return ScanOutcome(
            scan_id, status, checked, changes, len(successful_dirs), len(failed_dirs),
            tuple(result["errors"]),
        )

    def _walk(self, successful: set[str], failed: dict[str, str]):
        stack = [(self.content_dir, "")]
        while stack:
            directory, relative_dir = stack.pop()
            try:
                entries = os.scandir(directory)
            except OSError as exc:
                failed[relative_dir] = type(exc).__name__
                logger.warning("目录不可访问: %s", directory)
                continue
            try:
                with entries:
                    successful.add(relative_dir)
                    for entry in entries:
                        yield None, 1
                        try:
                            relative = entry.name if not relative_dir else f"{relative_dir}/{entry.name}"
                            if entry.is_symlink():
                                if relative not in self._warned_symlinks:
                                    logger.warning("忽略 Content 内符号链接: %s", entry.path)
                                    self._warned_symlinks.add(relative)
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append((Path(entry.path), relative))
                                continue
                            if not entry.is_file(follow_symlinks=False) or Path(entry.name).suffix.casefold() != ".zip":
                                continue
                            info = entry.stat(follow_symlinks=False)
                            yield DiscoveredFile(
                                relative,
                                FileSnapshot(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns),
                            ), 0
                        except OSError as exc:
                            failed[relative_dir] = type(exc).__name__
            except OSError as exc:
                successful.discard(relative_dir)
                failed[relative_dir] = type(exc).__name__

    def _reconcile_batch(self, batch: list[DiscoveredFile], scan_id: str) -> int:
        paths = [item.relative_path for item in batch]
        identities = {(item.snapshot.device, item.snapshot.inode, item.snapshot.size) for item in batch}
        identity_filters = [
            (File.device == device) & (File.inode == inode) & (File.size == size)
            for device, inode, size in identities
        ]
        changed = 0
        current = utc_now()
        record_filter = (
            File.present.is_(True),
            or_(File.relative_path.in_(paths), or_(*identity_filters)),
        )
        with Session(self.engine) as read_session:
            candidates = list(read_session.scalars(select(File).where(*record_filter)))
            candidate_paths = {
                record.id: record.relative_path
                for record in candidates
            }
            missing_cover_ids = {
                record.id for record in candidates
                if record.status == AnalysisStatus.READY
                and record.cover_status == CoverStatus.COMPLETE
                and record.cover_path
                and _cover_is_missing(self.tasks.cover_dir, record.cover_path)
            }
        missing_candidate_ids = {
            record_id for record_id, relative_path in candidate_paths.items()
            if not (self.content_dir / relative_path).exists()
        }
        with self.writer.transaction() as session:
            records = session.scalars(select(File).where(*record_filter)).all()
            by_path = {record.relative_path: record for record in records if record.relative_path in paths}
            active_by_file = {
                task.file_id: task for task in session.scalars(
                    select(Task).where(
                        Task.file_id.in_([record.id for record in records]),
                        Task.status.in_(ACTIVE_TASK_STATUSES),
                    )
                )
            }
            by_identity: dict[tuple[int, int, int], list[File]] = {}
            for record in records:
                by_identity.setdefault((record.device, record.inode, record.size), []).append(record)

            for item in batch:
                snapshot = item.snapshot
                record = by_path.get(item.relative_path)
                if record is not None and record.inode != snapshot.inode:
                    self._mark_deleted(record, current, active_by_file.get(record.id))
                    record = None
                    changed += 1
                if record is None:
                    candidates = [
                        candidate for candidate in by_identity.get((snapshot.device, snapshot.inode, snapshot.size), [])
                        if candidate.id in missing_candidate_ids
                    ]
                    if len(candidates) == 1:
                        record = candidates[0]
                        old_name = PurePosixPath(record.relative_path).name
                        record.relative_path = item.relative_path
                        record.storage_unavailable = False
                        record.deleted_at = None
                        if old_name != PurePosixPath(item.relative_path).name or record.parser_version < PARSER_VERSION:
                            parsed = parse_filename(Path(item.relative_path).name)
                            _apply_identity_and_parse(record, snapshot, item.relative_path, parsed)
                            _replace_tags(session, record, parsed)
                        self._move_active_task(active_by_file.get(record.id), item.relative_path)
                        changed += 1
                    else:
                        record = self._new_waiting_file(session, item)
                        record.last_seen_scan_id = scan_id
                        by_identity.setdefault((snapshot.device, snapshot.inode, snapshot.size), []).append(record)
                        changed += 1
                        self._enqueue(session, record, item.relative_path, reset_retries=True, task=None)
                        continue

                record.storage_unavailable = False
                record.present = True
                record.deleted_at = None
                record.last_seen_scan_id = scan_id
                if (record.size, record.modified_ns) != (snapshot.size, snapshot.modified_ns):
                    if record.status != AnalysisStatus.READY:
                        _apply_identity_and_parse(record, snapshot, item.relative_path, parse_filename(Path(item.relative_path).name))
                    self._enqueue(
                        session, record, item.relative_path, reset_retries=True,
                        task=active_by_file.get(record.id),
                    )
                    changed += 1
                elif record.status == AnalysisStatus.WAITING_STABLE:
                    self._enqueue(
                        session, record, item.relative_path, reset_retries=False,
                        task=active_by_file.get(record.id),
                    )
                elif record.parser_version < PARSER_VERSION:
                    parsed = parse_filename(Path(item.relative_path).name)
                    _apply_identity_and_parse(record, snapshot, item.relative_path, parsed)
                    _replace_tags(session, record, parsed)
                    changed += 1
                elif record.id in missing_cover_ids:
                    # Covers are disposable cache data and may be omitted from a
                    # cold backup. Re-analyze the unchanged ZIP to recreate it.
                    record.cover_status = CoverStatus.NOT_GENERATED
                    record.cover_path = None
                    self._enqueue(
                        session, record, item.relative_path, reset_retries=False,
                        task=active_by_file.get(record.id),
                    )
                    changed += 1
        return changed

    def _reconcile_directories(
        self, successful: set[str], failed: dict[str, str], root_failed: bool
    ) -> int:
        """Mirror visible real directories without deleting inaccessible subtrees."""
        changed = 0
        visible = {path for path in successful if path}
        failed_prefixes = tuple(path for path in failed if path)
        with self.writer.transaction() as session:
            existing = {item.relative_path: item for item in session.scalars(select(Directory))}
            for path in visible:
                parent = PurePosixPath(path).parent.as_posix()
                parent = "" if parent == "." else parent
                name = PurePosixPath(path).name
                item = existing.get(path)
                if item is None:
                    session.add(Directory(
                        relative_path=path, parent_path=parent, name_nfc=unicodedata.normalize("NFC", name),
                        name_casefold=normalized_casefold(name),
                        natural_sort_key=natural_sort_bytes(name), present=True,
                        storage_unavailable=False,
                    ))
                    changed += 1
                elif not item.present or item.storage_unavailable:
                    item.present = True
                    item.storage_unavailable = False
                    changed += 1
            for path, item in existing.items():
                if path in visible:
                    continue
                inaccessible = root_failed or any(
                    path == prefix or path.startswith(f"{prefix}/") for prefix in failed_prefixes
                )
                if inaccessible:
                    if not item.storage_unavailable:
                        item.storage_unavailable = True
                        changed += 1
                elif item.present:
                    item.present = False
                    changed += 1
        return changed

    def _new_waiting_file(self, session: Session, item: DiscoveredFile) -> File:
        parsed = parse_filename(Path(item.relative_path).name)
        record = File(
            relative_path=item.relative_path,
            status=AnalysisStatus.WAITING_STABLE,
            cover_status=CoverStatus.NOT_GENERATED,
            cover_path=None,
            last_error=None,
        )
        _apply_identity_and_parse(record, item.snapshot, item.relative_path, parsed)
        session.add(record)
        session.flush()
        return record

    def _enqueue(
        self, session: Session, record: File, relative_path: str, *, reset_retries: bool,
        task: Task | None,
    ) -> Task:
        current = utc_now()
        if task is None:
            task = Task(
                id=str(uuid.uuid4()), file_id=record.id, relative_path=relative_path,
                task_type="analyze_zip", status="waiting_stable", priority=10,
                retry_count=0, stable_count=0,
                next_run_at=current + timedelta(seconds=self.tasks.stable_interval),
            )
            session.add(task)
        else:
            task.relative_path = relative_path
            task.updated_at = current
            if task.status != "analyzing":
                task.status = "waiting_stable"
                task.next_run_at = current + timedelta(seconds=self.tasks.stable_interval)
                task.stable_count = 0
            if reset_retries:
                task.retry_count = 0
                task.last_error = None
        if record.status != AnalysisStatus.READY:
            record.status = AnalysisStatus.WAITING_STABLE
        return task

    @staticmethod
    def _move_active_task(task: Task | None, relative_path: str) -> None:
        if task is not None:
            task.relative_path = relative_path

    @staticmethod
    def _mark_deleted(record: File, current, task: Task | None) -> None:
        record.present = False
        record.storage_unavailable = False
        record.deleted_at = current
        if task is not None:
            task.status = "cancelled"
            task.next_run_at = None
            task.completed_at = current

    def _reconcile_missing(self, scan_id: str, failed_dirs: dict[str, str], root_failed: bool) -> int:
        changed = 0
        current = utc_now()
        failed_prefixes = tuple(path for path in failed_dirs if path)
        last_id = ""
        while True:
            with self.writer.transaction() as session:
                records = session.scalars(
                    select(File).where(
                        File.present.is_(True), File.id > last_id,
                        or_(File.last_seen_scan_id.is_(None), File.last_seen_scan_id != scan_id),
                    )
                    .order_by(File.id).limit(BATCH_SIZE)
                ).all()
                if not records:
                    break
                last_id = records[-1].id
                active_by_file = {
                    task.file_id: task for task in session.scalars(
                        select(Task).where(
                            Task.file_id.in_([record.id for record in records]),
                            Task.status.in_(ACTIVE_TASK_STATUSES),
                        )
                    )
                }
                for record in records:
                    inaccessible = root_failed or any(
                        record.relative_path == prefix or record.relative_path.startswith(f"{prefix}/")
                        for prefix in failed_prefixes
                    )
                    if inaccessible:
                        if not record.storage_unavailable:
                            record.storage_unavailable = True
                            changed += 1
                    else:
                        self._mark_deleted(record, current, active_by_file.get(record.id))
                        changed += 1
        return changed

    def latest_status(self) -> dict[str, object]:
        with Session(self.engine) as session:
            scan = session.scalar(select(Scan).order_by(Scan.started_at.desc()).limit(1))
            if scan is None:
                return {"status": "not_started", "follow_up_pending": self._follow_up}
            result = json.loads(scan.result_json)
            return {
                "id": scan.id,
                "status": "running" if self._running else scan.status,
                "started_at": scan.started_at,
                "completed_at": scan.completed_at,
                "checked_entries": scan.checked_entries,
                "changes_found": scan.changes_found,
                "follow_up_pending": self._follow_up,
                **result,
            }
