from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select

from dokura.metadata.analysis_service import FileSnapshot, PreparedAnalysis, parsed_json
from dokura.metadata.database import WriteScheduler
from dokura.metadata.models import AnalysisStatus, CoverStatus, File, FileTag, Page, Tag
from dokura.metadata.natural_sort import natural_sort_bytes, normalized_casefold


def _apply_identity_and_parse(record: File, snapshot: FileSnapshot, relative_path: str, parsed) -> None:
    confidence_json, warnings_json, unclassified_json = parsed_json(parsed)
    record.relative_path = relative_path
    record.original_filename = parsed.original_filename
    record.filename_nfc = parsed.basename
    record.filename_casefold = normalized_casefold(parsed.basename)
    record.natural_sort_key = natural_sort_bytes(relative_path)
    record.device = snapshot.device
    record.inode = snapshot.inode
    record.size = snapshot.size
    record.modified_ns = snapshot.modified_ns
    record.content_version = snapshot.content_version
    record.title = parsed.title
    record.title_casefold = normalized_casefold(parsed.title)
    record.event = parsed.event
    record.creator_raw = parsed.creator_raw
    record.circle = parsed.circle
    record.translated = parsed.translated
    record.parser_version = parsed.parser_version
    record.parse_confidence = parsed.parse_confidence
    record.field_confidence_json = confidence_json
    record.parse_warnings_json = warnings_json
    record.unclassified_tags_json = unclassified_json


def _replace_tags(session, record: File, parsed) -> None:
    session.execute(delete(FileTag).where(FileTag.file_id == record.id))
    values = (("artist", value) for value in parsed.artists)
    values = (*values, *(("source", value) for value in parsed.source_works), *(("language", value) for value in parsed.languages))
    for category, value in dict.fromkeys(values):
        tag = session.scalar(select(Tag).where(Tag.category == category, Tag.value == value))
        if tag is None:
            tag = Tag(category=category, value=value, value_casefold=normalized_casefold(value))
            session.add(tag)
            session.flush()
        session.add(FileTag(file_id=record.id, tag_id=tag.id))


def commit_analysis(
    prepared: PreparedAnalysis,
    relative_path: str,
    cover_dir: Path,
    writer: WriteScheduler,
) -> File:
    """Atomically replace metadata after all slow work and final file validation."""
    final_cover: Path | None = None
    if prepared.temporary_cover is not None:
        cover_dir.mkdir(parents=True, exist_ok=True)
        final_cover = cover_dir / f"{prepared.snapshot.content_version}.jpg"
        prepared.temporary_cover.replace(final_cover)

    parsed = prepared.parsed
    with writer.transaction() as session:
        record = session.scalar(select(File).where(File.relative_path == relative_path, File.present.is_(True)))
        if record is None:
            record = File(relative_path=relative_path)
            session.add(record)
        _apply_identity_and_parse(record, prepared.snapshot, relative_path, parsed)
        record.present = True
        record.storage_unavailable = False
        record.deleted_at = None
        record.status = AnalysisStatus.READY if prepared.archive.has_valid_content else AnalysisStatus.NO_VALID_CONTENT
        record.cover_status = CoverStatus.COMPLETE if final_cover else CoverStatus.GENERATION_FAILED
        record.cover_path = str(final_cover.relative_to(cover_dir.parent)) if final_cover else None
        record.last_error = None
        session.flush()

        session.execute(delete(Page).where(Page.file_id == record.id))
        for page in prepared.archive.pages:
            reason = prepared.archive.unavailable_pages.get(page.number)
            session.add(Page(
                file_id=record.id, page_number=page.number, entry_name=page.entry_name,
                uncompressed_size=page.uncompressed_size, crc32=page.crc32,
                unavailable=reason is not None, unavailable_reason=reason,
            ))
        _replace_tags(session, record, parsed)
        session.flush()
        return record


def commit_archive_failure(
    snapshot: FileSnapshot,
    relative_path: str,
    parsed,
    error_code: str,
    writer: WriteScheduler,
) -> File:
    """Persist a stable archive failure without replacing prior usable metadata."""
    with writer.transaction() as session:
        record = session.scalar(select(File).where(File.relative_path == relative_path, File.present.is_(True)))
        if record is None:
            record = File(relative_path=relative_path)
            session.add(record)
        if record.status != AnalysisStatus.READY:
            _apply_identity_and_parse(record, snapshot, relative_path, parsed)
            record.status = AnalysisStatus.FAILED
            record.cover_status = CoverStatus.NOT_GENERATED
            record.cover_path = None
        record.present = True
        record.storage_unavailable = False
        record.deleted_at = None
        record.last_error = error_code
        session.flush()
        return record
