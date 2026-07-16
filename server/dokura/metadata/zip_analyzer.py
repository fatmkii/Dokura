from __future__ import annotations

import io
import os
import posixpath
import struct
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from dokura.metadata.natural_sort import natural_path_key

MAX_ENTRY_SIZE = 512 * 1024 * 1024
MAX_TOTAL_SIZE = 20 * 1024 * 1024 * 1024
RATIO_TOTAL_THRESHOLD = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_DIMENSION = 32_768
MAX_PIXELS = 100_000_000
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class ZipAnalysisError(Exception):
    """A deterministic archive-level failure safe to persist as failed."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class DeterministicPageError(Exception):
    """Content proves that this stable page cannot be used."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


class TemporaryReadError(Exception):
    """The read failed without proving that page content is invalid."""


@dataclass(frozen=True, slots=True)
class ArchivePage:
    number: int
    entry_name: str
    uncompressed_size: int
    crc32: int


@dataclass(frozen=True, slots=True)
class ZipAnalysis:
    pages: tuple[ArchivePage, ...]
    cover_page: int | None
    cover_jpeg: bytes | None
    unavailable_pages: dict[int, str]

    @property
    def has_valid_content(self) -> bool:
        return bool(self.pages) and len(self.unavailable_pages) < len(self.pages)


def _safe_name(raw_name: str) -> str:
    name = raw_name.replace("\\", "/")
    if name.startswith("/") or (len(name) >= 2 and name[1] == ":"):
        raise ZipAnalysisError("UNSAFE_ZIP_PATH", raw_name)
    stack: list[str] = []
    for segment in name.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not stack:
                raise ZipAnalysisError("UNSAFE_ZIP_PATH", raw_name)
            stack.pop()
        else:
            stack.append(segment)
    normalized = posixpath.join(*stack) if stack else ""
    if not normalized:
        return ""
    return normalized


def _is_candidate(info: zipfile.ZipInfo) -> tuple[bool, str]:
    normalized = _safe_name(info.filename)
    if info.is_dir() or not normalized:
        return False, normalized
    segments = normalized.split("/")
    if any(segment.startswith(".") or segment.casefold() == "__macosx" for segment in segments):
        return False, normalized
    return Path(segments[-1]).suffix.casefold() in IMAGE_EXTENSIONS, normalized


def _validate_ranges(archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> None:
    ranges: list[tuple[int, int, str]] = []
    fp = archive.fp
    if fp is None:
        raise ZipAnalysisError("INVALID_ZIP_STRUCTURE")
    for info in infos:
        fp.seek(info.header_offset)
        header = fp.read(30)
        if len(header) != 30 or header[:4] != b"PK\x03\x04":
            raise ZipAnalysisError("INVALID_ZIP_STRUCTURE", info.filename)
        filename_length, extra_length = struct.unpack_from("<HH", header, 26)
        start = info.header_offset + 30 + filename_length + extra_length
        end = start + info.compress_size
        if end > archive.start_dir:
            raise ZipAnalysisError("INVALID_ZIP_STRUCTURE", info.filename)
        ranges.append((start, end, info.filename))
    ranges.sort()
    for previous, current in zip(ranges, ranges[1:], strict=False):
        if current[0] < previous[1]:
            raise ZipAnalysisError("OVERLAPPING_ZIP_ENTRIES", f"{previous[2]} / {current[2]}")


def inspect_archive(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    infos = archive.infolist()
    total = sum(info.file_size for info in infos)
    compressed = sum(info.compress_size for info in infos)
    if any(info.file_size > MAX_ENTRY_SIZE for info in infos):
        raise ZipAnalysisError("ZIP_ENTRY_TOO_LARGE")
    if total > MAX_TOTAL_SIZE:
        raise ZipAnalysisError("ZIP_TOTAL_TOO_LARGE")
    if total > RATIO_TOTAL_THRESHOLD and total > max(compressed, 1) * MAX_COMPRESSION_RATIO:
        raise ZipAnalysisError("ZIP_COMPRESSION_RATIO_EXCEEDED")
    _validate_ranges(archive, infos)

    candidates: list[tuple[zipfile.ZipInfo, str]] = []
    for info in infos:
        if info.flag_bits & 0x1:
            raise ZipAnalysisError("ENCRYPTED_ZIP", info.filename)
        candidate, normalized = _is_candidate(info)
        if candidate:
            candidates.append((info, normalized))
    candidates.sort(key=lambda item: natural_path_key(item[1]))
    return candidates


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > MAX_ENTRY_SIZE:
        raise DeterministicPageError("PAGE_TOO_LARGE")
    output = io.BytesIO()
    try:
        with archive.open(info) as source:
            remaining = MAX_ENTRY_SIZE + 1
            while chunk := source.read(min(1024 * 1024, remaining)):
                output.write(chunk)
                remaining -= len(chunk)
                if remaining <= 0:
                    raise DeterministicPageError("PAGE_TOO_LARGE")
    except DeterministicPageError:
        raise
    except (zipfile.BadZipFile, RuntimeError, EOFError, zlib.error) as exc:
        raise DeterministicPageError("CORRUPT_PAGE_DATA", str(exc)) from exc
    except OSError as exc:
        raise TemporaryReadError(str(exc)) from exc
    return output.getvalue()
def _validated_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        if width <= 0 or height <= 0 or width > MAX_DIMENSION or height > MAX_DIMENSION:
            raise DeterministicPageError("UNSAFE_IMAGE_DIMENSIONS")
        if width * height > MAX_PIXELS:
            raise DeterministicPageError("IMAGE_PIXEL_LIMIT_EXCEEDED")
        image.load()
        if image.format not in {"JPEG", "PNG"}:
            raise DeterministicPageError("INVALID_IMAGE_FORMAT")
        return image
    except DeterministicPageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DeterministicPageError("INVALID_IMAGE_DATA", str(exc)) from exc


def _make_cover(image: Image.Image) -> bytes:
    image = ImageOps.exif_transpose(image)
    image.thumbnail((720, 720), Image.Resampling.LANCZOS)
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    destination = io.BytesIO()
    image.save(destination, format="JPEG", quality=85)
    return destination.getvalue()


def analyze_zip(path: Path, yield_check: Callable[[], None] | None = None) -> ZipAnalysis:
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = inspect_archive(archive)
            pages = tuple(
                ArchivePage(number=index, entry_name=info.filename, uncompressed_size=info.file_size, crc32=info.CRC)
                for index, (info, _normalized) in enumerate(candidates, start=1)
            )
        if yield_check is not None:
            yield_check()
        with zipfile.ZipFile(path) as archive:
            unavailable: dict[int, str] = {}
            for page, (info, _normalized) in zip(pages, candidates, strict=True):
                try:
                    try:
                        current_info = archive.getinfo(info.filename)
                    except KeyError as exc:
                        raise TemporaryReadError("ZIP 内容可能已变化") from exc
                    image = _validated_image(_read_entry(archive, current_info))
                    return ZipAnalysis(pages, page.number, _make_cover(image), unavailable)
                except DeterministicPageError as exc:
                    unavailable[page.number] = exc.code
            return ZipAnalysis(pages, None, None, unavailable)
    except ZipAnalysisError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError) as exc:
        raise ZipAnalysisError("INVALID_OR_ENCRYPTED_ZIP", str(exc)) from exc
    except OSError as exc:
        raise TemporaryReadError(str(exc)) from exc


def read_page(path: Path, entry_name: str) -> bytes:
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                info = archive.getinfo(entry_name)
            except KeyError as exc:
                raise TemporaryReadError("ZIP 内容可能已变化") from exc
            data = _read_entry(archive, info)
            _validated_image(data)
            return data
    except DeterministicPageError:
        raise
    except TemporaryReadError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise TemporaryReadError(str(exc)) from exc
