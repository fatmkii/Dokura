from __future__ import annotations

from pathlib import Path

from dokura.metadata.analysis_service import FileChangedDuringAnalysis, FileSnapshot, prepare_analysis
from dokura.metadata.database import WriteScheduler
from dokura.metadata.filename_parser import parse_filename
from dokura.metadata.models import File
from dokura.metadata.repository import commit_analysis, commit_archive_failure
from dokura.metadata.zip_analyzer import ZipAnalysisError


def process_zip(zip_path: Path, relative_path: str, cover_dir: Path, writer: WriteScheduler) -> File:
    """Analyze one stable ZIP and persist only a complete result or explained stable failure."""
    before = FileSnapshot.read(zip_path)
    try:
        prepared = prepare_analysis(zip_path, cover_dir)
    except ZipAnalysisError as exc:
        try:
            after = FileSnapshot.read(zip_path)
        except OSError:
            raise FileChangedDuringAnalysis from None
        if before != after:
            raise FileChangedDuringAnalysis
        return commit_archive_failure(after, relative_path, parse_filename(zip_path.name), exc.code, writer)
    return commit_analysis(prepared, relative_path, cover_dir, writer)
