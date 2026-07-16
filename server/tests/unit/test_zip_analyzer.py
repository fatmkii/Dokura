from __future__ import annotations

import binascii
import io
import struct
import zipfile
import zlib
from pathlib import Path

import pytest
from PIL import Image

from dokura.metadata import zip_analyzer
from dokura.metadata.zip_analyzer import TemporaryReadError, ZipAnalysisError, analyze_zip, read_page


def image_bytes(format: str = "PNG", size: tuple[int, int] = (32, 20), mode: str = "RGB") -> bytes:
    image = Image.new(mode, size, (255, 0, 0, 128) if mode == "RGBA" else "red")
    output = io.BytesIO()
    image.save(output, format=format)
    return output.getvalue()


def make_zip(path: Path, entries: dict[str, bytes], compression: int = zipfile.ZIP_STORED) -> None:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def huge_png(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", binascii.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    iend = b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
    return signature + ihdr + iend


def corrupt_first_payload(path: Path, needle: bytes) -> None:
    data = bytearray(path.read_bytes())
    position = data.index(needle)
    data[position] ^= 0xFF
    path.write_bytes(data)


def mark_encrypted(path: Path) -> None:
    data = bytearray(path.read_bytes())
    local = data.index(b"PK\x03\x04")
    central = data.index(b"PK\x01\x02")
    struct.pack_into("<H", data, local + 6, struct.unpack_from("<H", data, local + 6)[0] | 1)
    struct.pack_into("<H", data, central + 8, struct.unpack_from("<H", data, central + 8)[0] | 1)
    path.write_bytes(data)


def overlap_second_entry(path: Path) -> None:
    data = bytearray(path.read_bytes())
    first = data.index(b"PK\x01\x02")
    second = data.index(b"PK\x01\x02", first + 4)
    first_offset = struct.unpack_from("<I", data, first + 42)[0]
    struct.pack_into("<I", data, second + 42, first_offset)
    path.write_bytes(data)


def test_filters_entries_and_sorts_by_path_segments(tmp_path: Path) -> None:
    path = tmp_path / "book.zip"
    make_zip(path, {
        "10.png": image_bytes(), "2.png": image_bytes(), "folder/10.jpg": image_bytes("JPEG"),
        "folder/2.jpg": image_bytes("JPEG"), ".hidden/1.jpg": image_bytes("JPEG"),
        "__MACOSX/x.jpg": image_bytes("JPEG"), "notes.txt": b"ignored",
    })
    result = analyze_zip(path)
    assert [page.entry_name for page in result.pages] == ["2.png", "10.png", "folder/2.jpg", "folder/10.jpg"]


@pytest.mark.parametrize("name", ["../../escape.jpg", "/absolute.jpg", "C:\\absolute.jpg"])
def test_rejects_unsafe_paths(tmp_path: Path, name: str) -> None:
    path = tmp_path / "unsafe.zip"
    make_zip(path, {name: image_bytes()})
    with pytest.raises(ZipAnalysisError, match="escape|absolute") as caught:
        analyze_zip(path)
    assert caught.value.code == "UNSAFE_ZIP_PATH"


def test_no_image_zip_has_no_valid_content(tmp_path: Path) -> None:
    path = tmp_path / "empty.zip"
    make_zip(path, {"readme.txt": b"text"})
    result = analyze_zip(path)
    assert result.pages == ()
    assert not result.has_valid_content


def test_corrupt_zip_is_archive_failure(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.zip"
    path.write_bytes(b"not a zip")
    with pytest.raises(ZipAnalysisError) as caught:
        analyze_zip(path)
    assert caught.value.code == "INVALID_OR_ENCRYPTED_ZIP"


def test_encrypted_candidate_is_archive_failure(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.zip"
    make_zip(path, {"1.jpg": image_bytes("JPEG")})
    mark_encrypted(path)
    with pytest.raises(ZipAnalysisError) as caught:
        analyze_zip(path)
    assert caught.value.code == "ENCRYPTED_ZIP"


def test_overlapping_entry_data_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "overlap.zip"
    make_zip(path, {"1.jpg": image_bytes("JPEG"), "2.jpg": image_bytes("JPEG")})
    overlap_second_entry(path)
    with pytest.raises(ZipAnalysisError) as caught:
        analyze_zip(path)
    assert caught.value.code == "OVERLAPPING_ZIP_ENTRIES"


def test_crc_failure_keeps_page_number_and_uses_next_cover(tmp_path: Path) -> None:
    path = tmp_path / "crc.zip"
    first = image_bytes("PNG", (21, 13))
    make_zip(path, {"1.png": first, "2.jpg": image_bytes("JPEG", (44, 22))})
    corrupt_first_payload(path, first)
    result = analyze_zip(path)
    assert len(result.pages) == 2
    assert result.unavailable_pages == {1: "CORRUPT_PAGE_DATA"}
    assert result.cover_page == 2
    assert result.has_valid_content


def test_pixel_bomb_is_deterministic_and_next_page_becomes_cover(tmp_path: Path) -> None:
    path = tmp_path / "pixels.zip"
    make_zip(path, {"1.png": huge_png(32769, 1), "2.png": image_bytes(size=(1600, 800), mode="RGBA")})
    result = analyze_zip(path)
    assert result.unavailable_pages == {1: "UNSAFE_IMAGE_DIMENSIONS"}
    assert result.cover_page == 2
    with Image.open(io.BytesIO(result.cover_jpeg)) as cover:
        assert cover.format == "JPEG"
        assert cover.size == (720, 360)
        assert cover.mode == "RGB"
        assert cover.getpixel((100, 100))[1] > 100  # 半透明红色已与白底合成


def test_cover_does_not_upscale_and_uses_quality_85(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "small.zip"
    make_zip(path, {"1.png": image_bytes(size=(32, 20))})
    captured: dict[str, object] = {}
    original_save = Image.Image.save

    def recording_save(self, fp, format=None, **params):
        captured.update(format=format, **params)
        return original_save(self, fp, format=format, **params)

    monkeypatch.setattr(Image.Image, "save", recording_save)
    result = analyze_zip(path)
    assert captured["format"] == "JPEG"
    assert captured["quality"] == 85
    with Image.open(io.BytesIO(result.cover_jpeg)) as cover:
        assert cover.size == (32, 20)


def test_declared_limits_and_compression_ratio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry_path = tmp_path / "entry.zip"
    make_zip(entry_path, {"1.png": image_bytes()})
    monkeypatch.setattr(zip_analyzer, "MAX_ENTRY_SIZE", 4)
    with pytest.raises(ZipAnalysisError) as caught:
        analyze_zip(entry_path)
    assert caught.value.code == "ZIP_ENTRY_TOO_LARGE"

    total_path = tmp_path / "total.zip"
    make_zip(total_path, {"1.jpg": b"123456", "2.jpg": b"123456"})
    monkeypatch.setattr(zip_analyzer, "MAX_ENTRY_SIZE", 100)
    monkeypatch.setattr(zip_analyzer, "MAX_TOTAL_SIZE", 10)
    with pytest.raises(ZipAnalysisError) as caught:
        analyze_zip(total_path)
    assert caught.value.code == "ZIP_TOTAL_TOO_LARGE"

    ratio_path = tmp_path / "ratio.zip"
    make_zip(ratio_path, {"1.png": b"0" * 4096}, compression=zipfile.ZIP_DEFLATED)
    monkeypatch.setattr(zip_analyzer, "MAX_ENTRY_SIZE", 10_000)
    monkeypatch.setattr(zip_analyzer, "MAX_TOTAL_SIZE", 10_000)
    monkeypatch.setattr(zip_analyzer, "RATIO_TOTAL_THRESHOLD", 1)
    monkeypatch.setattr(zip_analyzer, "MAX_COMPRESSION_RATIO", 2)
    with pytest.raises(ZipAnalysisError) as caught:
        analyze_zip(ratio_path)
    assert caught.value.code == "ZIP_COMPRESSION_RATIO_EXCEEDED"


def test_page_content_error_and_temporary_archive_error_are_distinct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "book.zip"
    make_zip(path, {"1.jpg": b"not an image"})
    result = analyze_zip(path)
    assert result.unavailable_pages == {1: "INVALID_IMAGE_DATA"}
    assert not result.has_valid_content

    class UnavailableZip:
        def __init__(self, _path: Path) -> None:
            raise PermissionError("NAS unavailable")

    monkeypatch.setattr(zipfile, "ZipFile", UnavailableZip)
    with pytest.raises(TemporaryReadError):
        read_page(path, "1.jpg")
