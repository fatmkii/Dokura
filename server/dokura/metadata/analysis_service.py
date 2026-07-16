from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from dokura.metadata.filename_parser import ParsedFilename, parse_filename
from dokura.metadata.zip_analyzer import ZipAnalysis, analyze_zip


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    device: int
    inode: int
    size: int
    modified_ns: int

    @classmethod
    def read(cls, path: Path) -> "FileSnapshot":
        stat = path.stat()
        return cls(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    @property
    def content_version(self) -> str:
        raw = f"{self.device}:{self.inode}:{self.size}:{self.modified_ns}".encode()
        return hashlib.sha256(raw).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class PreparedAnalysis:
    snapshot: FileSnapshot
    parsed: ParsedFilename
    archive: ZipAnalysis
    temporary_cover: Path | None


class FileChangedDuringAnalysis(Exception):
    pass


def prepare_analysis(zip_path: Path, cover_dir: Path) -> PreparedAnalysis:
    """Perform all ZIP/image/filesystem I/O before a database transaction is opened."""
    before = FileSnapshot.read(zip_path)
    parsed = parse_filename(zip_path.name)
    archive = analyze_zip(zip_path)
    temporary: Path | None = None
    if archive.cover_jpeg is not None:
        temporary_dir = cover_dir / "tmp"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        temporary = temporary_dir / f"{before.content_version}.{os.getpid()}.cover.tmp"
        with temporary.open("xb") as output:
            output.write(archive.cover_jpeg)
            output.flush()
            os.fsync(output.fileno())
    try:
        after = FileSnapshot.read(zip_path)
    except OSError:
        if temporary:
            temporary.unlink(missing_ok=True)
        raise FileChangedDuringAnalysis from None
    if after != before:
        if temporary:
            temporary.unlink(missing_ok=True)
        raise FileChangedDuringAnalysis
    return PreparedAnalysis(before, parsed, archive, temporary)


def parsed_json(parsed: ParsedFilename) -> tuple[str, str, str]:
    return (
        json.dumps(parsed.field_confidence, ensure_ascii=False, sort_keys=True),
        json.dumps(parsed.parse_warnings, ensure_ascii=False),
        json.dumps(parsed.unclassified_tags, ensure_ascii=False),
    )
