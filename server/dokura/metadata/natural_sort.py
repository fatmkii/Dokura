from __future__ import annotations

import re
import unicodedata


def normalized_casefold(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def natural_path_key(path: str) -> tuple[tuple[tuple[int, object], ...], ...]:
    normalized = path.replace("\\", "/")
    segments = normalized.split("/")
    result = []
    for segment in segments:
        pieces: list[tuple[int, object]] = []
        for piece in re.split(r"(\d+)", normalized_casefold(segment)):
            if not piece:
                continue
            pieces.append((0, int(piece)) if piece.isdigit() else (1, piece))
        pieces.append((2, segment.encode("utf-8")))
        result.append(tuple(pieces))
    return tuple(result)


def natural_sort_bytes(path: str) -> bytes:
    """A SQLite-sortable encoding matching ``natural_path_key`` ordering."""
    encoded = bytearray()
    for segment in path.replace("\\", "/").split("/"):
        for piece in re.split(r"(\d+)", normalized_casefold(segment)):
            if not piece:
                continue
            if piece.isdigit():
                number = piece.lstrip("0") or "0"
                encoded.extend(b"N")
                encoded.extend(len(number).to_bytes(4, "big"))
                encoded.extend(number.encode("ascii"))
            else:
                encoded.extend(b"T")
                encoded.extend(piece.encode("utf-8"))
                encoded.append(0)
        encoded.extend(b"\xfe")
        encoded.extend(segment.encode("utf-8"))
        encoded.extend(b"\x00\xff")
    return bytes(encoded)
