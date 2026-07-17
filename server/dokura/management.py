from __future__ import annotations

import os
import stat
import threading
import unicodedata
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from dokura.catalog import CatalogQuery, matching_file_ids
from dokura.metadata.analysis_service import FileSnapshot
from dokura.metadata.database import WriteScheduler
from dokura.metadata.filename_parser import parse_filename
from dokura.metadata.models import AnalysisStatus, Directory, File, Task, utc_now
from dokura.metadata.natural_sort import natural_sort_bytes, normalized_casefold
from dokura.metadata.repository import _apply_identity_and_parse, _replace_tags
from dokura.metadata.tasks import ACTIVE_TASK_STATUSES


SNAPSHOT_LIFETIME = timedelta(minutes=30)
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
INVALID_NAME_CHARS = set('/\\<>:"|?*')


class ManagementError(ValueError):
    pass


class BusyError(ManagementError, TimeoutError):
    pass


@dataclass(frozen=True, slots=True)
class SelectionSnapshot:
    id: str
    session_id: str
    file_ids: tuple[str, ...]
    query: CatalogQuery
    created_at: datetime
    last_used_at: datetime


class FileOperationLocks:
    """Per-UUID locks shared by analysis, original reads, and management."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def acquire(self, file_id: str, timeout: float = 5) -> threading.Lock:
        with self._guard:
            lock = self._locks.setdefault(file_id, threading.Lock())
        if not lock.acquire(timeout=timeout):
            raise BusyError("文件正在处理，请稍后重试")
        return lock


def validate_name(value: str, *, zip_basename: bool = False) -> str:
    value = unicodedata.normalize("NFC", value.strip())
    if not value or value in {".", ".."}:
        raise ManagementError("名称不能为空或使用 .、..")
    if value[-1] in {" ", "."}:
        raise ManagementError("名称不能以空格或句点结尾")
    if any(character in INVALID_NAME_CHARS or ord(character) < 32 for character in value):
        raise ManagementError("名称包含不允许的字符")
    reserved_stem = value.split(".", 1)[0].upper()
    if reserved_stem in WINDOWS_RESERVED:
        raise ManagementError("名称是 Windows 保留名")
    final = f"{value}.zip" if zip_basename else value
    if len(final.encode("utf-8")) > 255:
        raise ManagementError("名称按 UTF-8 编码后不能超过 255 字节")
    return value


def _validate_relative_length(value: str) -> None:
    if len(value.encode("utf-8")) > 4095:
        raise ManagementError("相对路径按 UTF-8 编码后不能超过 4095 字节")


class ManagementService:
    def __init__(
        self, engine: Engine, writer: WriteScheduler, content_dir: Path,
        scans, tasks, locks: FileOperationLocks,
    ) -> None:
        self.engine = engine
        self.writer = writer
        self.content_dir = content_dir
        self.scans = scans
        self.tasks = tasks
        self.locks = locks
        self._snapshots: dict[str, SelectionSnapshot] = {}
        self._snapshot_guard = threading.Lock()
        self._directory_lock = threading.Lock()

    def _root(self) -> Path:
        try:
            return self.content_dir.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ManagementError("Content 根目录不存在或无法访问") from exc

    def _real_existing(self, relative: str, *, directory: bool | None = None) -> Path:
        candidate = self.content_dir / relative
        try:
            info = candidate.lstat()
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ManagementError("目标不存在或无法访问") from exc
        if stat.S_ISLNK(info.st_mode) or not resolved.is_relative_to(self._root()):
            raise ManagementError("目标真实路径不在 Content 内")
        if directory is True and not stat.S_ISDIR(info.st_mode):
            raise ManagementError("目标不是文件夹")
        if directory is False and not stat.S_ISREG(info.st_mode):
            raise ManagementError("目标不是普通文件")
        return resolved

    @staticmethod
    def _parent(path: str) -> str:
        parent = PurePosixPath(path).parent.as_posix()
        return "" if parent == "." else parent

    def _target(self, parent: str, name: str) -> tuple[str, Path]:
        parent_path = self._real_existing(parent, directory=True) if parent else self._root()
        relative = name if not parent else f"{parent}/{name}"
        _validate_relative_length(relative)
        candidate = parent_path / name
        if candidate.exists() or candidate.is_symlink():
            raise ManagementError("目标名称已存在")
        try:
            names = [entry.name.casefold() for entry in os.scandir(parent_path)]
        except OSError as exc:
            raise ManagementError("目标文件夹无法访问") from exc
        if name.casefold() in names:
            raise ManagementError("目标名称与现有项目冲突")
        return relative, candidate

    def _file(self, file_id: str) -> tuple[str, int, int]:
        with Session(self.engine) as session:
            item = session.scalar(select(File).where(File.id == file_id, File.present.is_(True)))
            if item is None:
                raise ManagementError("文件不存在")
            return item.relative_path, item.device, item.inode

    def _verify_file(self, file_id: str) -> tuple[Path, str]:
        relative, device, inode = self._file(file_id)
        path = self._real_existing(relative, directory=False)
        info = path.stat()
        if (info.st_dev, info.st_ino) != (device, inode):
            raise ManagementError("文件身份已经变化，请刷新后重试")
        return path, relative

    def create_snapshot(self, session_id: str, query: CatalogQuery) -> SelectionSnapshot:
        now = utc_now()
        snapshot = SelectionSnapshot(
            str(uuid.uuid4()), session_id, tuple(matching_file_ids(self.engine, query)),
            query, now, now,
        )
        with self._snapshot_guard:
            self._snapshots[session_id] = snapshot
        return snapshot

    def snapshot(self, session_id: str, *, touch: bool = True) -> SelectionSnapshot | None:
        with self._snapshot_guard:
            item = self._snapshots.get(session_id)
            if item is None:
                return None
            now = utc_now()
            last_used = item.last_used_at if item.last_used_at.tzinfo else item.last_used_at.replace(tzinfo=UTC)
            if now - last_used >= SNAPSHOT_LIFETIME:
                self._snapshots.pop(session_id, None)
                return None
            if touch:
                item = replace(item, last_used_at=now)
                self._snapshots[session_id] = item
            return item

    def release_snapshot(self, session_id: str) -> None:
        with self._snapshot_guard:
            self._snapshots.pop(session_id, None)

    def _snapshot_current(self, session_id: str) -> tuple[SelectionSnapshot, list[File]]:
        snapshot = self.snapshot(session_id)
        if snapshot is None:
            raise ManagementError("选择快照已过期，请重新选择")
        current_ids = set(matching_file_ids(self.engine, snapshot.query)) & set(snapshot.file_ids)
        with Session(self.engine) as session:
            records = list(session.scalars(select(File).where(File.id.in_(current_ids), File.present.is_(True))))
        return snapshot, records

    def delete_preview(self, session_id: str) -> dict[str, object]:
        snapshot, records = self._snapshot_current(session_id)
        return {
            "snapshot_id": snapshot.id,
            "file_count": len(records),
            "total_bytes": sum(item.size for item in records),
        }

    def delete_snapshot(self, session_id: str, snapshot_id: str, file_count: int, total_bytes: int) -> dict[str, object]:
        snapshot, records = self._snapshot_current(session_id)
        actual = (len(records), sum(item.size for item in records))
        if snapshot.id != snapshot_id or actual != (file_count, total_bytes):
            return {"reconfirmation_required": True, "snapshot_id": snapshot.id, "file_count": actual[0], "total_bytes": actual[1]}
        result = self._operate_files([item.id for item in records], self._delete_one)
        self.release_snapshot(session_id)
        self.scans.request_scan()
        return {"reconfirmation_required": False, **result}

    def move_snapshot(self, session_id: str, target_directory: str) -> dict[str, object]:
        _snapshot, records = self._snapshot_current(session_id)
        result = self.move_files([item.id for item in records], target_directory)
        self.release_snapshot(session_id)
        return result

    def _operate_files(self, file_ids: list[str], operation) -> dict[str, object]:
        succeeded: list[str] = []
        failed: list[dict[str, str]] = []
        for file_id in file_ids:
            lock = None
            try:
                lock = self.locks.acquire(file_id)
                operation(file_id)
                succeeded.append(file_id)
            except (ManagementError, OSError) as exc:
                failed.append({"id": file_id, "reason": str(exc) or type(exc).__name__})
            finally:
                if lock is not None:
                    lock.release()
        return {"success_count": len(succeeded), "failure_count": len(failed), "succeeded": succeeded, "failed": failed}

    def _delete_one(self, file_id: str) -> None:
        path, relative = self._verify_file(file_id)
        path.unlink()
        current = utc_now()
        with self.writer.transaction() as session:
            item = session.get(File, file_id)
            if item is not None:
                item.present = False
                item.deleted_at = current
            for task in session.scalars(select(Task).where(Task.file_id == file_id, Task.status.in_(ACTIVE_TASK_STATUSES))):
                task.status = "cancelled"
                task.next_run_at = None
                task.completed_at = current

    def delete_file(self, file_id: str) -> dict[str, object]:
        result = self._operate_files([file_id], self._delete_one)
        self.scans.request_scan()
        return result

    def rename_file(self, file_id: str, basename: str) -> dict[str, str]:
        basename = validate_name(basename, zip_basename=True)
        lock = self.locks.acquire(file_id)
        try:
            source, relative = self._verify_file(file_id)
            name = f"{basename}{source.suffix}"
            parent = self._parent(relative)
            if source.name.casefold() == name.casefold():
                new_relative = name if not parent else f"{parent}/{name}"
                target = source.with_name(name)
            else:
                new_relative, target = self._target(parent, name)
            source.replace(target)
            try:
                self._update_file_path(file_id, new_relative, renamed=True)
            except Exception:
                target.replace(source)
                raise
            return {"id": file_id, "relative_path": new_relative}
        finally:
            lock.release()

    def move_files(self, file_ids: list[str], target_directory: str) -> dict[str, object]:
        target_directory = target_directory.strip("/")
        target = self._real_existing(target_directory, directory=True) if target_directory else self._root()

        def move(file_id: str) -> None:
            source, relative = self._verify_file(file_id)
            if source.stat().st_dev != target.stat().st_dev:
                raise ManagementError("首版不支持跨文件系统移动")
            new_relative, destination = self._target(target_directory, source.name)
            source.replace(destination)
            try:
                self._update_file_path(file_id, new_relative, renamed=False)
            except Exception:
                destination.replace(source)
                raise

        result = self._operate_files(file_ids, move)
        self.scans.request_scan()
        return result

    def _update_file_path(self, file_id: str, relative: str, *, renamed: bool) -> None:
        snapshot = FileSnapshot.read(self.content_dir / relative)
        with self.writer.transaction() as session:
            item = session.get(File, file_id)
            if item is None:
                raise ManagementError("文件不存在")
            if renamed:
                parsed = parse_filename(PurePosixPath(relative).name)
                _apply_identity_and_parse(item, snapshot, relative, parsed)
                _replace_tags(session, item, parsed)
            else:
                item.relative_path = relative
                item.parent_path = self._parent(relative)
                item.device, item.inode = snapshot.device, snapshot.inode
            for task in session.scalars(select(Task).where(Task.file_id == file_id, Task.status.in_(ACTIVE_TASK_STATUSES))):
                task.relative_path = relative

    def create_directory(self, parent: str, name: str) -> dict[str, str]:
        name = validate_name(name)
        relative, target = self._target(parent.strip("/"), name)
        target.mkdir()
        self.scans.request_scan()
        return {"relative_path": relative}

    def rename_directory(self, relative: str, name: str) -> dict[str, str]:
        relative = relative.strip("/")
        name = validate_name(name)
        return self._move_directory(relative, self._parent(relative), name)

    def move_directory(self, relative: str, target_parent: str) -> dict[str, str]:
        relative = relative.strip("/")
        return self._move_directory(relative, target_parent.strip("/"), PurePosixPath(relative).name)

    def _move_directory(self, relative: str, target_parent: str, name: str) -> dict[str, str]:
        if not relative:
            raise ManagementError("不能移动或重命名 Content 根目录")
        with self._directory_lock:
            source = self._real_existing(relative, directory=True)
            target_dir = self._real_existing(target_parent, directory=True) if target_parent else self._root()
            if target_parent == relative or target_parent.startswith(f"{relative}/"):
                raise ManagementError("不能将文件夹移入自身或其子目录")
            if source.stat().st_dev != target_dir.stat().st_dev:
                raise ManagementError("首版不支持跨文件系统移动")
            if self._parent(relative) == target_parent and source.name.casefold() == name.casefold():
                new_relative = name if not target_parent else f"{target_parent}/{name}"
                target = source.with_name(name)
            else:
                new_relative, target = self._target(target_parent, name)
            with Session(self.engine) as session:
                descendants = list(session.scalars(select(File).where(File.present.is_(True), File.relative_path.like(f"{relative}/%"))))
            for item in descendants:
                suffix = item.relative_path[len(relative):]
                _validate_relative_length(f"{new_relative}{suffix}")
            acquired: list[threading.Lock] = []
            try:
                for item in descendants:
                    acquired.append(self.locks.acquire(item.id))
                source.replace(target)
                try:
                    with self.writer.transaction() as session:
                        files = session.scalars(select(File).where(File.relative_path.like(f"{relative}/%"))).all()
                        ids = [item.id for item in files]
                        for item in files:
                            item.relative_path = f"{new_relative}{item.relative_path[len(relative):]}"
                            item.parent_path = self._parent(item.relative_path)
                        directories = session.scalars(select(Directory).where((Directory.relative_path == relative) | Directory.relative_path.like(f"{relative}/%"))).all()
                        for item in directories:
                            item.relative_path = f"{new_relative}{item.relative_path[len(relative):]}"
                            item.parent_path = self._parent(item.relative_path)
                            item.name_nfc = PurePosixPath(item.relative_path).name
                            item.name_casefold = normalized_casefold(item.name_nfc)
                            item.natural_sort_key = natural_sort_bytes(item.name_nfc)
                        if ids:
                            for task in session.scalars(select(Task).where(Task.file_id.in_(ids), Task.status.in_(ACTIVE_TASK_STATUSES))):
                                if task.relative_path:
                                    task.relative_path = f"{new_relative}{task.relative_path[len(relative):]}"
                except Exception:
                    target.replace(source)
                    raise
            finally:
                for lock in reversed(acquired):
                    lock.release()
            self.scans.request_scan()
            return {"relative_path": new_relative}

    def delete_directory(self, relative: str) -> None:
        relative = relative.strip("/")
        if not relative:
            raise ManagementError("不能删除 Content 根目录")
        with self._directory_lock:
            path = self._real_existing(relative, directory=True)
            try:
                with os.scandir(path) as entries:
                    if next(entries, None) is not None:
                        raise ManagementError("只能删除实际为空的文件夹")
                path.rmdir()
            except ManagementError:
                raise
            except OSError as exc:
                raise ManagementError("文件夹删除失败，内容可能已经变化") from exc
            self.scans.request_scan()

    def reprocess(self, file_id: str) -> dict[str, bool]:
        self._verify_file(file_id)
        accepted = self._enqueue_reprocess([file_id], priority=20)
        return {"accepted": accepted > 0}

    def retry_failed(self) -> dict[str, int]:
        with Session(self.engine) as session:
            ids = set(session.scalars(select(File.id).where(File.present.is_(True), File.status == AnalysisStatus.FAILED)))
            ids.update(session.scalars(
                select(Task.file_id).join(File, File.id == Task.file_id).where(
                    Task.status == "failed", Task.file_id.is_not(None), File.present.is_(True)
                )
            ))
            ids.discard(None)
        added = self._enqueue_reprocess(list(ids), priority=5)
        return {"eligible": len(ids), "added": added, "skipped": len(ids) - added}

    def _enqueue_reprocess(self, file_ids: list[str], *, priority: int) -> int:
        now = utc_now()
        added = 0
        with self.writer.transaction() as session:
            for file_id in file_ids:
                item = session.get(File, file_id)
                active = session.scalar(select(Task.id).where(Task.file_id == file_id, Task.status.in_(ACTIVE_TASK_STATUSES)))
                if item is None or not item.present or active:
                    continue
                session.add(Task(
                    id=str(uuid.uuid4()), file_id=file_id, relative_path=item.relative_path,
                    task_type="reprocess_zip", status="waiting_stable", priority=priority,
                    retry_count=0, stable_count=0, next_run_at=now,
                    created_at=now, updated_at=now,
                ))
                item.status = AnalysisStatus.WAITING_STABLE
                added += 1
        if added:
            self.tasks.wake()
        return added
