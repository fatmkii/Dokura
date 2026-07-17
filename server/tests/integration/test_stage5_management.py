from __future__ import annotations

import logging
import zipfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dokura.catalog import CatalogQuery
from dokura.logfiles import LogManager
from dokura.management import BusyError, FileOperationLocks, ManagementError, ManagementService, validate_name
from dokura.metadata.analysis_service import FileSnapshot
from dokura.metadata.database import WriteScheduler, create_database_engine
from dokura.metadata.migrations import upgrade_database
from dokura.metadata.models import AnalysisStatus, CoverStatus, Directory, File, Task
from dokura.metadata.natural_sort import natural_sort_bytes, normalized_casefold


class StubScans:
    def __init__(self) -> None:
        self.requests = 0

    def request_scan(self) -> bool:
        self.requests += 1
        return True


class StubTasks:
    def __init__(self) -> None:
        self.wakes = 0

    def wake(self) -> None:
        self.wakes += 1


@pytest.fixture
def management(tmp_path: Path):
    content = tmp_path / "content"
    metadata = tmp_path / "metadata"
    content.mkdir()
    metadata.mkdir()
    upgrade_database(metadata / "dokura.sqlite3")
    engine = create_database_engine(metadata / "dokura.sqlite3")
    writer = WriteScheduler(engine)
    scans = StubScans()
    tasks = StubTasks()
    service = ManagementService(engine, writer, content, scans, tasks, FileOperationLocks())
    yield service, content, engine, writer, scans, tasks
    engine.dispose()


def seed_file(content: Path, writer: WriteScheduler, relative: str, *, rating: int = 0) -> str:
    path = content / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("1.jpg", b"image")
    snapshot = FileSnapshot.read(path)
    file_id = f"00000000-0000-0000-0000-{snapshot.inode % 10**12:012d}"
    name = path.name
    with writer.transaction() as session:
        parent = Path(relative).parent.as_posix()
        parent = "" if parent == "." else parent
        if parent and session.get(Directory, parent) is None:
            session.add(Directory(
                relative_path=parent, parent_path="", name_nfc=Path(parent).name,
                name_casefold=normalized_casefold(Path(parent).name),
                natural_sort_key=natural_sort_bytes(Path(parent).name), present=True,
                storage_unavailable=False,
            ))
        session.add(File(
            id=file_id, relative_path=relative, parent_path=parent,
            original_filename=name, filename_nfc=name,
            filename_casefold=normalized_casefold(name), natural_sort_key=natural_sort_bytes(name),
            device=snapshot.device, inode=snapshot.inode, size=snapshot.size,
            modified_ns=snapshot.modified_ns, content_version=snapshot.content_version,
            status=AnalysisStatus.READY, cover_status=CoverStatus.COMPLETE,
            cover_path=f"covers/{file_id}.jpg", title=path.stem,
            title_casefold=normalized_casefold(path.stem), parser_version=1,
            parse_confidence=1.0, field_confidence_json="{}", parse_warnings_json="[]",
            unclassified_tags_json="[]", rating=rating, present=True,
            storage_unavailable=False,
        ))
    return file_id


@pytest.mark.parametrize("name", ["", ".", "..", "CON", "lpt9.txt", "bad/name", "bad*name", "tail."])
def test_name_validation_rejects_unsafe_or_reserved_names(name: str) -> None:
    with pytest.raises(ManagementError):
        validate_name(name)


def test_file_rename_move_and_delete_preserve_identity_until_permanent_deletion(management) -> None:
    service, content, engine, writer, scans, _tasks = management
    file_id = seed_file(content, writer, "来源/原名.zip", rating=4)
    service.create_directory("", "目标")

    renamed = service.rename_file(file_id, "新名称")
    assert renamed["relative_path"] == "来源/新名称.zip"
    moved = service.move_files([file_id], "目标")
    assert moved["success_count"] == 1
    assert (content / "目标/新名称.zip").is_file()
    with Session(engine) as session:
        item = session.get(File, file_id)
        assert (item.relative_path, item.rating, item.present) == ("目标/新名称.zip", 4, True)

    deleted = service.delete_file(file_id)
    assert deleted["success_count"] == 1
    assert not (content / "目标/新名称.zip").exists()
    with Session(engine) as session:
        assert session.get(File, file_id).present is False
    assert scans.requests >= 3


def test_batch_move_keeps_successes_and_explains_conflicts(management) -> None:
    service, content, engine, writer, _scans, _tasks = management
    first = seed_file(content, writer, "甲/同名.zip")
    second = seed_file(content, writer, "乙/同名.zip")
    service.create_directory("", "目标")

    result = service.move_files([first, second], "目标")
    assert (result["success_count"], result["failure_count"]) == (1, 1)
    assert "冲突" in result["failed"][0]["reason"] or "存在" in result["failed"][0]["reason"]
    with Session(engine) as session:
        records = {session.get(File, first).relative_path, session.get(File, second).relative_path}
    assert "目标/同名.zip" in records
    assert len(records) == 2


def test_directory_move_preserves_descendant_uuid_rating_cache_and_task_path(management) -> None:
    service, content, engine, writer, _scans, _tasks = management
    file_id = seed_file(content, writer, "父/子/作品.zip", rating=5)
    with writer.transaction() as session:
        session.add(Directory(
            relative_path="父", parent_path="", name_nfc="父", name_casefold="父",
            natural_sort_key=natural_sort_bytes("父"), present=True, storage_unavailable=False,
        ))
        session.add(Task(
            id="task", file_id=file_id, relative_path="父/子/作品.zip", task_type="analyze_zip",
            status="waiting_stable", priority=1, retry_count=0, stable_count=0,
        ))
    service.create_directory("", "归档")
    result = service.move_directory("父", "归档")
    assert result["relative_path"] == "归档/父"
    with Session(engine) as session:
        item = session.get(File, file_id)
        assert item.relative_path == "归档/父/子/作品.zip"
        assert item.rating == 5
        assert item.cover_path == f"covers/{file_id}.jpg"
        assert session.get(Task, "task").relative_path == item.relative_path


def test_empty_directory_delete_rejects_hidden_files_and_symlinks(management, tmp_path: Path) -> None:
    service, content, _engine, _writer, _scans, _tasks = management
    service.create_directory("", "非空")
    (content / "非空/.hidden").write_text("keep", encoding="utf-8")
    with pytest.raises(ManagementError, match="实际为空"):
        service.delete_directory("非空")
    (content / "非空/.hidden").unlink()
    outside = tmp_path / "outside"
    outside.mkdir()
    (content / "非空/link").symlink_to(outside)
    with pytest.raises(ManagementError, match="实际为空"):
        service.delete_directory("非空")


def test_selection_snapshot_revalidates_filter_and_requires_changed_statistics_confirmation(management) -> None:
    service, content, _engine, writer, _scans, _tasks = management
    first = seed_file(content, writer, "一.zip", rating=2)
    second = seed_file(content, writer, "二.zip", rating=3)
    snapshot = service.create_snapshot("session", CatalogQuery(rating_min=0, rating_max=3))
    preview = service.delete_preview("session")
    assert preview["file_count"] == 2

    with writer.transaction() as session:
        session.get(File, second).rating = 5
    changed = service.delete_snapshot(
        "session", snapshot.id, preview["file_count"], preview["total_bytes"]
    )
    assert changed["reconfirmation_required"] is True
    assert changed["file_count"] == 1
    assert (content / "一.zip").exists()

    confirmed = service.delete_snapshot(
        "session", snapshot.id, changed["file_count"], changed["total_bytes"]
    )
    assert confirmed["success_count"] == 1
    assert not (content / "一.zip").exists()
    assert (content / "二.zip").exists()


def test_selection_expiry_and_user_reprocess_commands(management) -> None:
    service, content, engine, writer, _scans, tasks = management
    file_id = seed_file(content, writer, "失败.zip")
    snapshot = service.create_snapshot("session", CatalogQuery())
    service._snapshots["session"] = replace(
        snapshot, last_used_at=snapshot.last_used_at - timedelta(minutes=31)
    )
    assert service.snapshot("session") is None

    with writer.transaction() as session:
        session.get(File, file_id).status = AnalysisStatus.FAILED
    result = service.retry_failed()
    assert result == {"eligible": 1, "added": 1, "skipped": 0}
    assert tasks.wakes == 1
    with Session(engine) as session:
        task = session.scalar(select(Task).where(Task.file_id == file_id))
        assert (task.task_type, task.status, task.retry_count) == ("reprocess_zip", "waiting_stable", 0)

    assert service.reprocess(file_id) == {"accepted": False}


def test_management_busy_timeout_is_reported_per_item(management, monkeypatch: pytest.MonkeyPatch) -> None:
    service, content, _engine, writer, _scans, _tasks = management
    file_id = seed_file(content, writer, "忙碌.zip")

    def busy(*_args, **_kwargs):
        raise BusyError("文件正在处理，请稍后重试")

    monkeypatch.setattr(service.locks, "acquire", busy)
    result = service.delete_file(file_id)
    assert result["failure_count"] == 1
    assert "正在处理" in result["failed"][0]["reason"]
    assert (content / "忙碌.zip").exists()


def test_path_escape_symlink_target_cross_filesystem_and_delete_race_are_rejected(management, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, content, engine, writer, _scans, _tasks = management
    file_id = seed_file(content, writer, "来源/安全.zip")
    service.create_directory("", "目标")
    outside = tmp_path / "outside"
    outside.mkdir()
    (content / "link").symlink_to(outside)

    with pytest.raises(ManagementError, match="Content"):
        service.create_directory("..", "逃逸")
    with pytest.raises(ManagementError, match="Content"):
        service.move_files([file_id], "link")

    source_device = (content / "来源/安全.zip").stat().st_dev
    real_stat = Path.stat

    def different_device(path: Path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == (content / "目标").resolve():
            return SimpleNamespace(st_dev=source_device + 1)
        return result

    monkeypatch.setattr(Path, "stat", different_device)
    result = service.move_files([file_id], "目标")
    assert result["failure_count"] == 1
    assert "跨文件系统" in result["failed"][0]["reason"]
    monkeypatch.setattr(Path, "stat", real_stat)

    source = content / "来源/安全.zip"
    real_unlink = Path.unlink

    def raced_unlink(path: Path, *args, **kwargs):
        if path == source.resolve():
            raise FileNotFoundError("external delete won")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", raced_unlink)
    result = service.delete_file(file_id)
    assert result["failure_count"] == 1
    with Session(engine) as session:
        assert session.get(File, file_id).present is True


def test_log_rotation_filtering_and_archive_keep_complete_files(tmp_path: Path) -> None:
    manager = LogManager(tmp_path, max_bytes=180, max_files=10)
    logger = logging.getLogger("dokura.stage5-test")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(manager.handler)
    try:
        for index in range(25):
            logger.info("entry-%02d %s", index, "x" * 45)
        logger.warning("final-warning")
    finally:
        logger.removeHandler(manager.handler)
        manager.handler.close()

    files = manager.handler.files()
    assert 2 <= len(files) <= 10
    warnings = manager.read({"WARNING"})["items"]
    assert len(warnings) == 1 and "final-warning" in warnings[0]["message"]
    archive = manager.archive()
    with zipfile.ZipFile(__import__("io").BytesIO(archive)) as zipped:
        assert sorted(zipped.namelist()) == sorted(path.name for path in files)
        assert all(zipped.read(name) == (tmp_path / "logs" / name).read_bytes() for name in zipped.namelist())
    restarted = LogManager(tmp_path, max_bytes=180, max_files=10)
    try:
        assert restarted.handler._path == files[-1]
    finally:
        restarted.handler.close()
