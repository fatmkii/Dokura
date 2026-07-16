from __future__ import annotations

import asyncio
import logging
import stat
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, Integer, cast, func, select
from sqlalchemy.orm import Session

from dokura.metadata.analysis_service import FileChangedDuringAnalysis, FileSnapshot
from dokura.metadata.database import WriteScheduler
from dokura.metadata.models import AnalysisStatus, File, Task, utc_now
from dokura.metadata.processor import process_zip
from dokura.metadata.zip_analyzer import TemporaryReadError


ACTIVE_TASK_STATUSES = ("waiting_stable", "retry_wait", "analyzing")
RETRY_DELAYS = (10, 60, 300)
logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ForegroundPressure:
    """Small shared gate used by later foreground endpoints and background stages."""

    def __init__(self) -> None:
        self._pending = 0
        self._clear = asyncio.Event()
        self._clear.set()
        self._background_clear = threading.Event()
        self._background_clear.set()

    @property
    def pending(self) -> bool:
        return self._pending > 0

    def enter(self) -> None:
        self._pending += 1
        self._clear.clear()
        self._background_clear.clear()

    def leave(self) -> None:
        self._pending = max(0, self._pending - 1)
        if not self._pending:
            self._clear.set()
            self._background_clear.set()

    async def wait_until_clear(self) -> None:
        await self._clear.wait()

    def wait_background(self) -> None:
        self._background_clear.wait()


class TaskScheduler:
    """One durable expiry scheduler for stability checks, retries and ZIP analysis."""

    def __init__(
        self,
        engine: Engine,
        writer: WriteScheduler,
        content_dir: Path,
        cover_dir: Path,
        pressure: ForegroundPressure,
        *,
        stable_interval: float = 5,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.engine = engine
        self.writer = writer
        self.content_dir = content_dir
        self.cover_dir = cover_dir
        self.pressure = pressure
        self.stable_interval = stable_interval
        self.now = now
        self._wake = asyncio.Event()
        self._analysis_lock = asyncio.Lock()
        self._stopped = False

    def wake(self) -> None:
        self._wake.set()

    def recover(self) -> None:
        """Return interrupted work to the queue without resetting retry allowance."""
        current = self.now()
        with self.writer.transaction() as session:
            tasks = session.scalars(select(Task).where(Task.status == "analyzing")).all()
            for task in tasks:
                task.status = "waiting_stable"
                task.stable_count = 0
                task.next_run_at = current
                task.started_at = None
                task.updated_at = current
                if task.file_id:
                    record = session.get(File, task.file_id)
                    if record is not None and record.status == AnalysisStatus.ANALYZING:
                        record.status = AnalysisStatus.WAITING_STABLE

    async def run(self) -> None:
        self.recover()
        while not self._stopped:
            due, delay = await asyncio.to_thread(self._next_due)
            if due is None:
                await self._wait(delay if delay > 0 else None)
                continue
            if delay > 0:
                await self._wait(delay)
                continue
            await self.pressure.wait_until_clear()
            await self._run_task(due)

    async def stop(self) -> None:
        self._stopped = True
        self.wake()

    async def _wait(self, timeout: float | None) -> None:
        self._wake.clear()
        try:
            if timeout is None:
                await self._wake.wait()
            else:
                await asyncio.wait_for(self._wake.wait(), timeout=max(0.01, timeout))
        except TimeoutError:
            pass

    def _next_due(self) -> tuple[str | None, float]:
        with Session(self.engine) as session:
            current = self.now()
            age_minutes = cast(
                (func.julianday(current) - func.julianday(Task.created_at)) * 24 * 60,
                Integer,
            )
            task = session.scalar(
                select(Task)
                .where(
                    Task.status.in_(("waiting_stable", "retry_wait")),
                    Task.next_run_at.is_not(None), Task.next_run_at <= current,
                )
                .order_by((Task.priority + age_minutes).desc(), Task.created_at)
                .limit(1)
            )
            if task is not None:
                return task.id, 0
            next_task = session.scalar(
                select(Task).where(
                    Task.status.in_(("waiting_stable", "retry_wait")), Task.next_run_at.is_not(None)
                ).order_by(Task.next_run_at).limit(1)
            )
            if next_task is None or next_task.next_run_at is None:
                return None, 0
            return None, (_as_utc(next_task.next_run_at) - _as_utc(current)).total_seconds()

    async def _run_task(self, task_id: str) -> None:
        async with self._analysis_lock:
            state = await asyncio.to_thread(self._check_stability, task_id)
            if state is None or state == "waiting":
                return
            path, relative_path = state
            try:
                await asyncio.to_thread(
                    process_zip, path, relative_path, self.cover_dir, self.writer,
                    yield_check=self.pressure.wait_background,
                )
            except FileChangedDuringAnalysis:
                await asyncio.to_thread(self._reschedule_after_change, task_id, path)
                self.wake()
                return
            except OSError as exc:
                await asyncio.to_thread(self._record_failure, task_id, "FILE_UNAVAILABLE", str(exc))
                self.wake()
                return
            except TemporaryReadError as exc:
                await asyncio.to_thread(self._record_failure, task_id, "FILE_UNAVAILABLE", str(exc))
                self.wake()
                return
            except Exception:
                logger.exception("ZIP 后台分析发生未预期错误", extra={"task_id": task_id})
                await asyncio.to_thread(self._record_failure, task_id, "INTERNAL_ANALYSIS_ERROR", None)
                self.wake()
                return
            await asyncio.to_thread(self._finish_from_record, task_id)
            self.wake()

    def _check_stability(self, task_id: str) -> tuple[Path, str] | str | None:
        with Session(self.engine) as session:
            task = session.get(Task, task_id)
            if task is None or task.status not in ("waiting_stable", "retry_wait") or not task.relative_path:
                return None
            relative_path = task.relative_path
        path = self.content_dir / relative_path
        try:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or path.suffix.casefold() != ".zip":
                self._cancel(task_id, deleted=True)
                return None
            snapshot = FileSnapshot.read(path)
        except FileNotFoundError:
            self._cancel(task_id, deleted=True)
            return None
        except OSError:
            self._reschedule_unavailable(task_id)
            return None

        current = self.now()
        with self.writer.transaction() as session:
            task = session.get(Task, task_id)
            if task is None or task.status not in ("waiting_stable", "retry_wait"):
                return None
            if task.status == "retry_wait":
                task.status = "waiting_stable"
                if (task.stable_size, task.stable_modified_ns) == (snapshot.size, snapshot.modified_ns):
                    task.stable_count = 3
                else:
                    task.retry_count = 0
                    task.stable_count = 1
                    task.stable_size = snapshot.size
                    task.stable_modified_ns = snapshot.modified_ns
            elif (task.stable_size, task.stable_modified_ns) == (snapshot.size, snapshot.modified_ns):
                task.stable_count += 1
            else:
                task.stable_size = snapshot.size
                task.stable_modified_ns = snapshot.modified_ns
                task.stable_count = 1
            task.updated_at = current
            if task.stable_count < 3:
                task.next_run_at = current + timedelta(seconds=self.stable_interval)
                return "waiting"
        try:
            final = FileSnapshot.read(path)
        except FileNotFoundError:
            self._cancel(task_id, deleted=True)
            return None
        except OSError:
            self._reschedule_unavailable(task_id)
            return None
        if final != snapshot:
            self._reschedule_changed(task_id)
            return "waiting"
        with self.writer.transaction() as session:
            task = session.get(Task, task_id)
            if (
                task is None or task.status != "waiting_stable" or task.stable_count < 3
                or (task.stable_size, task.stable_modified_ns) != (snapshot.size, snapshot.modified_ns)
            ):
                return None
            task.status = "analyzing"
            task.started_at = current
            task.next_run_at = None
            if task.file_id:
                record = session.get(File, task.file_id)
                if record is not None and record.status != AnalysisStatus.READY:
                    record.status = AnalysisStatus.ANALYZING
            return path, relative_path

    def _finish_from_record(self, task_id: str) -> None:
        current = self.now()
        with self.writer.transaction() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            record = session.get(File, task.file_id) if task.file_id else session.scalar(
                select(File).where(File.relative_path == task.relative_path, File.present.is_(True))
            )
            if record is None:
                task.status = "cancelled"
                task.completed_at = current
                return
            task.file_id = record.id
            if record.last_error:
                self._apply_failure(task, record, record.last_error, current)
                return
            task.status = "completed"
            task.completed_at = current
            task.updated_at = current
            task.last_error = None

    def _record_failure(self, task_id: str, code: str, detail: str | None) -> None:
        current = self.now()
        with self.writer.transaction() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            record = session.get(File, task.file_id) if task.file_id else None
            self._apply_failure(task, record, code, current)
            if detail:
                logger.warning("ZIP 分析失败: %s", detail, extra={"task_id": task_id})

    def _apply_failure(self, task: Task, record: File | None, code: str, current: datetime) -> None:
        task.last_error = code
        task.updated_at = current
        task.started_at = None
        if task.retry_count < len(RETRY_DELAYS):
            delay = RETRY_DELAYS[task.retry_count]
            task.retry_count += 1
            task.status = "retry_wait"
            task.next_run_at = current + timedelta(seconds=delay)
            task.stable_count = 0
            if record is not None and record.status != AnalysisStatus.READY:
                record.status = AnalysisStatus.RETRY_WAIT
                record.last_error = code
        else:
            task.status = "failed"
            task.next_run_at = None
            task.completed_at = current
            if record is not None and record.status != AnalysisStatus.READY:
                record.status = AnalysisStatus.FAILED
                record.last_error = code

    def _reschedule_changed(self, task_id: str) -> None:
        current = self.now()
        with self.writer.transaction() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            task.status = "waiting_stable"
            task.next_run_at = current + timedelta(seconds=self.stable_interval)
            task.stable_count = 0
            task.started_at = None
            task.updated_at = current

    def _reschedule_after_change(self, task_id: str, path: Path) -> None:
        try:
            FileSnapshot.read(path)
        except FileNotFoundError:
            self._cancel(task_id, deleted=True)
        except OSError:
            self._reschedule_unavailable(task_id)
        else:
            self._reschedule_changed(task_id)

    def _reschedule_unavailable(self, task_id: str) -> None:
        current = self.now()
        with self.writer.transaction() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            task.status = "waiting_stable"
            task.next_run_at = current + timedelta(seconds=self.stable_interval)
            task.updated_at = current
            if task.file_id:
                record = session.get(File, task.file_id)
                if record is not None:
                    record.storage_unavailable = True

    def _cancel(self, task_id: str, *, deleted: bool) -> None:
        current = self.now()
        with self.writer.transaction() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            task.status = "cancelled"
            task.next_run_at = None
            task.completed_at = current
            task.updated_at = current
            if deleted and task.file_id:
                record = session.get(File, task.file_id)
                if record is not None:
                    record.present = False
                    record.storage_unavailable = False
                    record.deleted_at = current
