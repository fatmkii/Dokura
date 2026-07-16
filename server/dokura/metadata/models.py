from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AnalysisStatus(enum.StrEnum):
    WAITING_STABLE = "waiting_stable"
    ANALYZING = "analyzing"
    READY = "ready"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    NO_VALID_CONTENT = "no_valid_content"


class CoverStatus(enum.StrEnum):
    NOT_GENERATED = "not_generated"
    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETE = "complete"
    GENERATION_FAILED = "generation_failed"


def utc_now() -> datetime:
    return datetime.now(UTC)


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    relative_path: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(Text)
    filename_nfc: Mapped[str] = mapped_column(Text)
    filename_casefold: Mapped[str] = mapped_column(Text, index=True)
    natural_sort_key: Mapped[bytes] = mapped_column(LargeBinary)
    device: Mapped[int] = mapped_column(Integer)
    inode: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    modified_ns: Mapped[int] = mapped_column(Integer)
    content_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[AnalysisStatus] = mapped_column(Enum(AnalysisStatus, values_callable=lambda items: [item.value for item in items]), index=True)
    cover_status: Mapped[CoverStatus] = mapped_column(Enum(CoverStatus, values_callable=lambda items: [item.value for item in items]))
    cover_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    title_casefold: Mapped[str] = mapped_column(Text, index=True)
    event: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    circle: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    parser_version: Mapped[int] = mapped_column(Integer)
    parse_confidence: Mapped[float] = mapped_column(Float)
    field_confidence_json: Mapped[str] = mapped_column(Text, default="{}")
    parse_warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    unclassified_tags_json: Mapped[str] = mapped_column(Text, default="[]")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)
    present: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    storage_unavailable: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_scan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    pages: Mapped[list[Page]] = relationship(cascade="all, delete-orphan", back_populates="file")
    tags: Mapped[list[FileTag]] = relationship(cascade="all, delete-orphan", back_populates="file")

    __table_args__ = (
        Index("ix_files_identity", "device", "inode", "size"),
        Index("ix_files_visible_path", "present", "relative_path"),
    )


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    entry_name: Mapped[str] = mapped_column(Text)
    uncompressed_size: Mapped[int] = mapped_column(Integer)
    crc32: Mapped[int] = mapped_column(Integer)
    unavailable: Mapped[bool] = mapped_column(Boolean, default=False)
    unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    file: Mapped[File] = relationship(back_populates="pages")
    __table_args__ = (UniqueConstraint("file_id", "page_number"),)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(Text)
    value_casefold: Mapped[str] = mapped_column(Text, index=True)
    __table_args__ = (UniqueConstraint("category", "value"),)


class FileTag(Base):
    __tablename__ = "file_tags"

    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    file: Mapped[File] = relationship(back_populates="tags")


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    relative_path: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[int] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stable_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stable_modified_ns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stable_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Scan(Base):
    __tablename__ = "scans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checked_entries: Mapped[int] = mapped_column(Integer, default=0)
    changes_found: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[str] = mapped_column(Text, default="{}")


class WebSession(Base):
    __tablename__ = "web_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_used_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class CacheEntry(Base):
    __tablename__ = "cache_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    relative_path: Mapped[str] = mapped_column(Text, unique=True)
    content_version: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)
