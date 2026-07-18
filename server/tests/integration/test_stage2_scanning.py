from __future__ import annotations

import asyncio
import hashlib
import io
import os
import threading
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from dokura.images import ImageService
from dokura.metadata.analysis_service import FileSnapshot, prepare_analysis
from dokura.metadata.cache_cleanup import CacheCleanupManager
from dokura.metadata.database import WriteScheduler, create_database_engine
from dokura.metadata.migrations import upgrade_database
from dokura.metadata.models import AnalysisStatus, File, FileTag, Tag, Task
from dokura.metadata.repository import commit_analysis
from dokura.metadata.scanning import ScanCoordinator, _cover_is_missing
from dokura.metadata.tasks import ForegroundPressure, TaskScheduler
from dokura.metadata.watcher import EventWindow
from watchfiles import Change


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (12, 16), "green").save(output, "PNG")
    return output.getvalue()


def _write_zip(path: Path, payload: bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        path.write_bytes(payload)
        return
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("1.png", _png())


@pytest.fixture
def stage2(tmp_path: Path):
    content = tmp_path / "content"
    metadata = tmp_path / "metadata"
    content.mkdir()
    metadata.mkdir()
    database = metadata / "dokura.sqlite3"
    upgrade_database(database)
    engine = create_database_engine(database)
    writer = WriteScheduler(engine)
    pressure = ForegroundPressure()
    tasks = TaskScheduler(engine, writer, content, metadata / "covers", pressure, stable_interval=0)
    scans = ScanCoordinator(engine, writer, content, tasks, pressure)
    yield content, metadata, engine, writer, tasks, scans
    engine.dispose()


def _analyze_pending(engine, tasks: TaskScheduler) -> str:
    with Session(engine) as session:
        task_id = session.scalar(
            select(Task.id).where(Task.status == "waiting_stable").order_by(Task.created_at)
        )
    assert task_id is not None
    asyncio.run(tasks._run_task(task_id))
    asyncio.run(tasks._run_task(task_id))
    asyncio.run(tasks._run_task(task_id))
    return task_id


def test_scan_filters_entries_and_analyzes_after_three_stable_checks(stage2) -> None:
    content, _metadata, engine, _writer, tasks, scans = stage2
    _write_zip(content / "book.ZIP")
    (content / "notes.txt").write_text("ignored")
    (content / "download.zip.part").write_text("ignored")
    (content / "book-link.zip").symlink_to(content / "book.ZIP")

    outcome = scans.scan_once()
    assert outcome.status == "completed"
    with Session(engine) as session:
        files = session.scalars(select(File)).all()
        assert [record.relative_path for record in files] == ["book.ZIP"]
        assert files[0].status == AnalysisStatus.WAITING_STABLE

    _analyze_pending(engine, tasks)
    with Session(engine) as session:
        record = session.scalar(select(File))
        task = session.scalar(select(Task))
        assert record is not None and record.status == AnalysisStatus.READY
        assert task is not None and task.status == "completed"


def test_scan_recreates_cover_omitted_from_cold_backup(stage2) -> None:
    content, metadata, engine, _writer, tasks, scans = stage2
    _write_zip(content / "book.zip")
    scans.scan_once()
    _analyze_pending(engine, tasks)
    with Session(engine) as session:
        record = session.scalar(select(File))
        cover = metadata / record.cover_path
        original_id = record.id
    cover.unlink()

    assert scans.scan_once().changes_found == 1
    _analyze_pending(engine, tasks)

    with Session(engine) as session:
        restored = session.get(File, original_id)
        assert restored.status == AnalysisStatus.READY
        assert (metadata / restored.cover_path).is_file()


def test_cover_recovery_never_probes_outside_metadata(tmp_path: Path) -> None:
    covers = tmp_path / "metadata" / "covers"
    covers.mkdir(parents=True)
    outside = tmp_path / "secret"
    outside.write_text("not a cover", encoding="utf-8")

    assert _cover_is_missing(covers, "../../secret") is True
    assert _cover_is_missing(covers, str(outside)) is True


def test_identity_rules_preserve_move_and_update_but_not_replacement(stage2) -> None:
    content, _metadata, engine, writer, tasks, scans = stage2
    original = content / "[Circle (Alice)] old.zip"
    _write_zip(original)
    scans.scan_once()
    _analyze_pending(engine, tasks)
    with writer.transaction() as session:
        record = session.scalar(select(File).where(File.present.is_(True)))
        original_id = record.id
        record.rating = 4

    renamed = content / "[Circle (Bob)] renamed.zip"
    original.rename(renamed)
    scans.scan_once()
    with Session(engine) as session:
        record = session.scalar(select(File).where(File.present.is_(True)))
        assert (record.id, record.relative_path, record.rating) == (original_id, "[Circle (Bob)] renamed.zip", 4)
        tags = session.scalars(
            select(Tag.value).join(FileTag, FileTag.tag_id == Tag.id).where(FileTag.file_id == record.id)
        ).all()
        assert tags == ["Bob"]

    with renamed.open("ab") as output:
        output.write(b"changed")
    scans.scan_once()
    with Session(engine) as session:
        record = session.get(File, original_id)
        assert record.present is True
        assert session.scalar(select(Task).where(Task.file_id == original_id, Task.status == "waiting_stable"))

    replacement = content / "replacement.tmp"
    _write_zip(replacement)
    os.replace(replacement, renamed)
    scans.scan_once()
    with Session(engine) as session:
        old = session.get(File, original_id)
        new = session.scalar(select(File).where(File.present.is_(True)))
        assert old.present is False
        assert new.id != original_id
        assert new.rating == 0


def test_scan_refreshes_mount_device_without_reanalyzing(stage2) -> None:
    content, metadata, engine, writer, _tasks, scans = stage2
    archive = content / "book.zip"
    _write_zip(archive)
    commit_analysis(prepare_analysis(archive, metadata / "covers"), "book.zip", metadata / "covers", writer)
    snapshot = FileSnapshot.read(archive)

    with writer.transaction() as session:
        record = session.scalar(select(File).where(File.present.is_(True)))
        file_id = record.id
        page_count = len(record.pages)
        record.device = snapshot.device + 1
        legacy = f"{record.device}:{snapshot.inode}:{snapshot.size}:{snapshot.modified_ns}".encode()
        record.content_version = hashlib.sha256(legacy).hexdigest()[:32]

    outcome = scans.scan_once()
    assert outcome.changes_found == 1

    with Session(engine) as session:
        record = session.get(File, file_id)
        assert record.device == snapshot.device
        assert record.content_version == snapshot.content_version
        assert len(record.pages) == page_count
        assert session.scalar(select(Task).where(Task.file_id == file_id, Task.status == "waiting_stable")) is None

    images = ImageService(engine, writer, content, metadata / "covers")
    assert images.page_record(file_id, 1) is not None


def test_content_version_is_independent_of_mount_device() -> None:
    first = FileSnapshot(1, 2, 3, 4)
    second = FileSnapshot(99, 2, 3, 4)

    assert first.content_version == second.content_version


def test_inaccessible_subtree_and_root_never_confirm_deletion(stage2, monkeypatch: pytest.MonkeyPatch) -> None:
    content, _metadata, engine, _writer, tasks, scans = stage2
    _write_zip(content / "blocked" / "book.zip")
    scans.scan_once()
    _analyze_pending(engine, tasks)
    with _writer.transaction() as session:
        record = session.scalar(select(File))
        identity = record.id
        cover_path = record.cover_path
        record.rating = 4

    real_scandir = os.scandir

    def inaccessible_subtree(path):
        if Path(path) == content / "blocked":
            raise PermissionError("offline")
        return real_scandir(path)

    monkeypatch.setattr("dokura.metadata.scanning.os.scandir", inaccessible_subtree)
    outcome = scans.scan_once()
    assert outcome.status == "partial"
    with Session(engine) as session:
        record = session.get(File, identity)
        assert record.present is True
        assert record.storage_unavailable is True

    def inaccessible_root(path):
        if Path(path) == content:
            raise PermissionError("offline")
        return real_scandir(path)

    monkeypatch.setattr("dokura.metadata.scanning.os.scandir", inaccessible_root)
    outcome = scans.scan_once()
    assert outcome.status == "failed"
    with Session(engine) as session:
        assert session.get(File, identity).present is True

    monkeypatch.setattr("dokura.metadata.scanning.os.scandir", real_scandir)
    assert scans.scan_once().status == "completed"
    with Session(engine) as session:
        record = session.get(File, identity)
        assert record.present is True
        assert record.storage_unavailable is False
        assert record.rating == 4
        assert record.cover_path == cover_path


def test_stability_permission_error_preserves_record(stage2, monkeypatch: pytest.MonkeyPatch) -> None:
    content, _metadata, engine, _writer, tasks, scans = stage2
    _write_zip(content / "book.zip")
    scans.scan_once()
    with Session(engine) as session:
        task = session.scalar(select(Task))
        task_id = task.id
        file_id = task.file_id

    def unavailable(_path):
        raise PermissionError("offline")

    monkeypatch.setattr("dokura.metadata.tasks.FileSnapshot.read", unavailable)
    asyncio.run(tasks._run_task(task_id))
    with Session(engine) as session:
        record = session.get(File, file_id)
        task = session.get(Task, task_id)
        assert record.present is True
        assert record.storage_unavailable is True
        assert task.status == "waiting_stable"


def test_failed_analysis_retries_three_times_and_recovery_keeps_budget(stage2) -> None:
    content, _metadata, engine, writer, tasks, scans = stage2
    _write_zip(content / "broken.zip", b"not a zip")
    scans.scan_once()
    task_id = _analyze_pending(engine, tasks)
    with Session(engine) as session:
        task = session.get(Task, task_id)
        assert (task.status, task.retry_count) == ("retry_wait", 1)

    asyncio.run(tasks._run_task(task_id))
    with writer.transaction() as session:
        task = session.get(Task, task_id)
        assert task.retry_count == 2
        task.status = "analyzing"
    tasks.recover()
    with Session(engine) as session:
        task = session.get(Task, task_id)
        assert (task.status, task.retry_count) == ("waiting_stable", 2)

    asyncio.run(tasks._run_task(task_id))
    asyncio.run(tasks._run_task(task_id))
    asyncio.run(tasks._run_task(task_id))
    asyncio.run(tasks._run_task(task_id))
    with Session(engine) as session:
        task = session.get(Task, task_id)
        record = session.get(File, task.file_id)
        assert (task.status, task.retry_count) == ("failed", 3)
        assert record.status == AnalysisStatus.FAILED


def test_scan_uses_bounded_batch_queries_instead_of_per_file_queries(stage2) -> None:
    content, _metadata, engine, _writer, _tasks, scans = stage2
    for index in range(401):
        (content / f"{index:04}.zip").write_bytes(b"")
    selects = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal selects
        normalized = statement.lstrip().upper()
        if normalized.startswith("SELECT") and (" FROM FILES" in normalized or " FROM TASKS" in normalized):
            selects += 1

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        scans.scan_once()
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)
    assert selects <= 12
    with Session(engine) as session:
        assert len(session.scalars(select(File)).all()) == 401
        assert len(session.scalars(select(Task)).all()) == 401


def test_duplicate_scans_deduplicate_tasks_and_continuous_write_resets_stability(stage2) -> None:
    content, _metadata, engine, _writer, tasks, scans = stage2
    path = content / "writing.zip"
    path.write_bytes(b"first")
    scans.scan_once()
    scans.scan_once()
    with Session(engine) as session:
        active = session.scalars(select(Task).where(Task.status == "waiting_stable")).all()
        assert len(active) == 1
        task_id = active[0].id

    asyncio.run(tasks._run_task(task_id))
    path.write_bytes(b"second and larger")
    asyncio.run(tasks._run_task(task_id))
    with Session(engine) as session:
        task = session.get(Task, task_id)
        assert task.stable_count == 1
        assert task.status == "waiting_stable"


def test_waiting_age_can_overtake_newer_priority(stage2) -> None:
    _content, _metadata, _engine, writer, tasks, _scans = stage2
    now = datetime.now(UTC)
    with writer.transaction() as session:
        session.add_all([
            Task(
                id="old", task_type="analyze_zip", status="waiting_stable", priority=0,
                retry_count=0, stable_count=0, next_run_at=now - timedelta(seconds=1),
                created_at=now - timedelta(minutes=20), updated_at=now,
            ),
            Task(
                id="new", task_type="analyze_zip", status="waiting_stable", priority=10,
                retry_count=0, stable_count=0, next_run_at=now - timedelta(seconds=1),
                created_at=now, updated_at=now,
            ),
        ])
    task_id, delay = tasks._next_due()
    assert (task_id, delay) == ("old", 0)


def test_one_second_event_window_normalizes_paths_and_keeps_latest_event(tmp_path: Path) -> None:
    window = EventWindow()
    path = str(tmp_path / "folder" / ".." / "book.zip")
    normalized = str(tmp_path / "book.zip")
    window.add({(Change.added, path)}, now=10)
    window.add({(Change.modified, normalized)}, now=10.9)
    assert window.pop_if_due(10.99) is None
    assert window.pop_if_due(11) == {normalized: Change.modified}


def test_concurrent_dispatch_cannot_analyze_the_same_uuid_in_parallel(
    stage2, monkeypatch: pytest.MonkeyPatch,
) -> None:
    content, _metadata, engine, _writer, tasks, scans = stage2
    _write_zip(content / "book.zip")
    scans.scan_once()
    with Session(engine) as session:
        task_id = session.scalar(select(Task.id))
    asyncio.run(tasks._run_task(task_id))
    asyncio.run(tasks._run_task(task_id))
    active = 0
    maximum = 0
    calls = 0
    guard = threading.Lock()

    def controlled_process(*_args, **_kwargs):
        nonlocal active, maximum, calls
        with guard:
            active += 1
            calls += 1
            maximum = max(maximum, active)
        time.sleep(0.05)
        with guard:
            active -= 1

    monkeypatch.setattr("dokura.metadata.tasks.process_zip", controlled_process)

    async def dispatch_twice() -> None:
        await asyncio.gather(tasks._run_task(task_id), tasks._run_task(task_id))

    asyncio.run(dispatch_twice())
    assert calls == 1
    assert maximum == 1


def test_foreground_pressure_pauses_scan_between_200_entry_batches(stage2) -> None:
    content, _metadata, engine, _writer, _tasks, scans = stage2
    for index in range(201):
        (content / f"{index:04}.zip").write_bytes(b"")
    scans.pressure.enter()
    worker = threading.Thread(target=scans.scan_once)
    worker.start()
    deadline = time.monotonic() + 3
    count = 0
    while time.monotonic() < deadline:
        with Session(engine) as session:
            count = len(session.scalars(select(File)).all())
        if count == 200:
            break
        time.sleep(0.01)
    assert count == 200
    assert worker.is_alive()
    scans.pressure.leave()
    worker.join(timeout=3)
    assert not worker.is_alive()
    with Session(engine) as session:
        assert len(session.scalars(select(File)).all()) == 201


def test_scan_requests_during_run_collapse_to_one_follow_up(stage2, monkeypatch: pytest.MonkeyPatch) -> None:
    _content, _metadata, _engine, _writer, _tasks, scans = stage2
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def controlled_scan():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            release.wait(timeout=3)

    monkeypatch.setattr(scans, "scan_once", controlled_scan)

    async def exercise() -> None:
        worker = asyncio.create_task(scans.run())
        await asyncio.to_thread(started.wait, 3)
        assert scans.request_scan() is True
        assert scans.request_scan() is False
        assert scans.request_scan() is False
        release.set()
        deadline = asyncio.get_running_loop().time() + 3
        while calls < 2 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(exercise())
    assert calls == 2


def test_cache_cleanup_requires_preview_and_revalidates_confirmed_deletion(stage2) -> None:
    content, metadata, engine, _writer, tasks, scans = stage2
    _write_zip(content / "book.zip")
    scans.scan_once()
    _analyze_pending(engine, tasks)
    with Session(engine) as session:
        record = session.scalar(select(File))
        file_id = record.id
        cover = metadata / record.cover_path
        assert cover.is_file()
    (content / "book.zip").unlink()
    scans.scan_once()

    old_tmp = metadata / "covers" / "tmp" / "orphan.cover.tmp"
    old_tmp.parent.mkdir(parents=True, exist_ok=True)
    old_tmp.write_bytes(b"temporary")
    old = time.time() - 25 * 60 * 60
    os.utime(old_tmp, (old, old))
    cleanup = CacheCleanupManager(engine, WriteScheduler(engine), metadata, content)
    preview = cleanup.preview()
    assert preview.file_count == 1
    assert preview.cache_file_count >= 2
    _write_zip(content / "book.zip")
    result = cleanup.execute(preview.confirmation_id)
    assert result["failure_count"] == 0
    assert result["busy_skipped_count"] == 1
    assert cover.exists()
    with Session(engine) as session:
        assert session.get(File, file_id) is not None

    (content / "book.zip").unlink()
    confirmed = cleanup.preview()
    result = cleanup.execute(confirmed.confirmation_id)
    assert result["failure_count"] == 0
    assert not cover.exists() and not old_tmp.exists()
    with Session(engine) as session:
        assert session.get(File, file_id) is None
    with pytest.raises(ValueError):
        cleanup.execute(preview.confirmation_id)
