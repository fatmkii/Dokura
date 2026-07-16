from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from dokura.metadata import analysis_service
from dokura.metadata.analysis_service import FileChangedDuringAnalysis, prepare_analysis
from dokura.metadata.database import WriteScheduler, create_database_engine
from dokura.metadata.migrations import upgrade_database
from dokura.metadata.models import AnalysisStatus, File, Page
from dokura.metadata.processor import process_zip
from dokura.metadata.repository import commit_analysis


def png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (20, 30), "blue").save(output, "PNG")
    return output.getvalue()


def write_book(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("1.png", png())


def test_analysis_io_finishes_before_short_atomic_metadata_commit(tmp_path: Path) -> None:
    zip_path = tmp_path / "[作者] 标题.zip"
    write_book(zip_path)
    covers = tmp_path / "metadata" / "covers"
    prepared = prepare_analysis(zip_path, covers)
    assert prepared.temporary_cover is not None
    assert prepared.temporary_cover.name.endswith(".tmp")

    db = tmp_path / "metadata" / "dokura.sqlite3"
    upgrade_database(db)
    engine = create_database_engine(db)
    try:
        record = commit_analysis(prepared, zip_path.name, covers, WriteScheduler(engine))
        assert record.status == AnalysisStatus.READY
        with Session(engine) as session:
            stored = session.scalar(select(File))
            assert stored is not None
            assert stored.title == "标题"
            assert stored.cover_path is not None
            assert "title" in json.loads(stored.field_confidence_json)
            pages = session.scalars(select(Page).order_by(Page.page_number)).all()
            assert [(page.page_number, page.unavailable) for page in pages] == [(1, False)]
        assert not prepared.temporary_cover.exists()
        assert len(list(covers.glob("*.jpg"))) == 1
    finally:
        engine.dispose()


def test_zip_modified_mid_analysis_discards_temporary_cover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zip_path = tmp_path / "book.zip"
    write_book(zip_path)
    covers = tmp_path / "covers"
    real_analyze = analysis_service.analyze_zip

    def modify_after_analysis(path: Path):
        result = real_analyze(path)
        with path.open("ab") as output:
            output.write(b"changed")
        return result

    monkeypatch.setattr(analysis_service, "analyze_zip", modify_after_analysis)
    with pytest.raises(FileChangedDuringAnalysis):
        prepare_analysis(zip_path, covers)
    assert not list(covers.rglob("*.tmp"))
    assert not list(covers.glob("*.jpg"))


@pytest.mark.parametrize("payload", [b"not a zip", b""])
def test_stable_broken_zip_enters_failed_state(tmp_path: Path, payload: bytes) -> None:
    zip_path = tmp_path / "broken.zip"
    zip_path.write_bytes(payload)
    db = tmp_path / "metadata.sqlite3"
    upgrade_database(db)
    engine = create_database_engine(db)
    try:
        record = process_zip(zip_path, zip_path.name, tmp_path / "covers", WriteScheduler(engine))
        assert record.status == AnalysisStatus.FAILED
        assert record.last_error == "INVALID_OR_ENCRYPTED_ZIP"
    finally:
        engine.dispose()


def test_failed_reanalysis_does_not_replace_ready_metadata(tmp_path: Path) -> None:
    zip_path = tmp_path / "[作者] 原标题.zip"
    write_book(zip_path)
    db = tmp_path / "metadata.sqlite3"
    upgrade_database(db)
    engine = create_database_engine(db)
    writer = WriteScheduler(engine)
    try:
        ready = process_zip(zip_path, zip_path.name, tmp_path / "covers", writer)
        assert ready.status == AnalysisStatus.READY
        zip_path.write_bytes(b"now corrupt")
        preserved = process_zip(zip_path, zip_path.name, tmp_path / "covers", writer)
        assert preserved.id == ready.id
        assert preserved.status == AnalysisStatus.READY
        assert preserved.title == "原标题"
        assert preserved.last_error == "INVALID_OR_ENCRYPTED_ZIP"
        with Session(engine) as session:
            assert session.scalar(select(Page)).entry_name == "1.png"
    finally:
        engine.dispose()
