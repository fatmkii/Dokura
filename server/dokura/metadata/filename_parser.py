from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

PARSER_VERSION = 1

_BRACKETS = {"(": ")", "（": "）", "[": "]", "［": "］", "【": "】", "〔": "〕"}
_ROUND = {"(", "（"}
_SQUARE = {"[", "［", "【", "〔"}
_CLOSERS = set(_BRACKETS.values())
_EVENT = re.compile(r"^(?:C\d+|COMITIA\d*|COMIC1|例大祭|サンクリ|.*(?:19|20)\d{2}.*)", re.IGNORECASE)
_LANGUAGES: dict[str, tuple[str | None, bool | None]] = {
    "中国翻訳": ("zh", True), "中国語": ("zh", None), "chinese": ("zh", None),
    "english": ("en", None), "英訳": ("en", True), "日本語": ("ja", None),
    "japanese": ("ja", None), "韓国語": ("ko", None), "korean": ("ko", None),
}
_EDITION = {"dl版", "digital", "デジタル版", "電子版", "冊子版", "scan"}
_GROUP_SUFFIXES = ("汉化组", "漢化組", "翻译组", "翻譯組", "掃圖組", "扫图组", "制作组", "製作組")


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    raw: str
    content: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ParsedFilename:
    original_filename: str
    basename: str
    extension: str
    event: str | None = None
    creator_raw: str | None = None
    circle: str | None = None
    artists: tuple[str, ...] = ()
    title: str = ""
    source_works: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    translated: bool | None = None
    unclassified_tags: tuple[str, ...] = ()
    parse_confidence: float = 0.0
    field_confidence: dict[str, float] = field(default_factory=dict)
    parse_warnings: tuple[str, ...] = ()
    parser_version: int = PARSER_VERSION


def tokenize(value: str) -> tuple[list[Token], list[str]]:
    tokens: list[Token] = []
    warnings: list[str] = []
    text_start = 0
    index = 0
    while index < len(value):
        opener = value[index]
        if opener not in _BRACKETS:
            if opener in _CLOSERS:
                warnings.append("UNMATCHED_BRACKET")
            index += 1
            continue
        if index > text_start:
            tokens.append(Token("TEXT", value[text_start:index], value[text_start:index], text_start, index))
        stack = [(_BRACKETS[opener], opener)]
        cursor = index + 1
        while cursor < len(value) and stack:
            char = value[cursor]
            if char in _BRACKETS:
                stack.append((_BRACKETS[char], char))
            elif char == stack[-1][0]:
                stack.pop()
            cursor += 1
        if stack:
            warnings.append("UNMATCHED_BRACKET")
            tokens.append(Token("TEXT", value[index:], value[index:], index, len(value)))
            return tokens, warnings
        raw = value[index:cursor]
        kind = "ROUND_BLOCK" if opener in _ROUND else "SQUARE_BLOCK"
        tokens.append(Token(kind, raw, raw[1:-1], index, cursor))
        index = cursor
        text_start = cursor
    if text_start < len(value):
        tokens.append(Token("TEXT", value[text_start:], value[text_start:], text_start, len(value)))
    return tokens, warnings


def _blank(token: Token) -> bool:
    return token.kind == "TEXT" and not token.raw.strip()


def _split_creator(value: str) -> tuple[str | None, tuple[str, ...]]:
    value = value.strip()
    match = re.match(r"^(.*?)\s*[（(]([^()（）]+)[)）]\s*$", value)
    if match and match.group(1).strip():
        artists = tuple(part.strip() for part in re.split(r"[,，、&＆×/]", match.group(2)) if part.strip())
        return match.group(1).strip(), artists
    # A lone creator is ambiguous. Latin-like names are kept as circle; others are an artist tag.
    if re.fullmatch(r"[\x00-\x7f]+", value):
        return value, ()
    artists = tuple(part.strip() for part in re.split(r"[,，、&＆×/]", value) if part.strip())
    return None, artists


def parse_filename(filename: str) -> ParsedFilename:
    original = filename
    suffix = Path(filename).suffix
    extension = suffix[1:].casefold() if suffix else ""
    basename = unicodedata.normalize("NFC", filename[:-len(suffix)] if suffix else filename).strip()
    tokens, warnings = tokenize(basename)
    used: set[int] = set()
    confidence: dict[str, float] = {"title": 0.96}
    event = creator = circle = None
    artists: tuple[str, ...] = ()

    first = next((i for i, token in enumerate(tokens) if not _blank(token)), None)
    if first is not None and tokens[first].kind == "ROUND_BLOCK" and _EVENT.match(tokens[first].content.strip()):
        event = tokens[first].content.strip()
        used.add(first)
        confidence["event"] = 0.99
        first = next((i for i in range(first + 1, len(tokens)) if not _blank(tokens[i])), None)
    if first is not None and tokens[first].kind == "SQUARE_BLOCK":
        creator = tokens[first].content.strip()
        circle, artists = _split_creator(creator)
        used.add(first)
        confidence["creator"] = 0.78

    trailing: list[int] = []
    i = len(tokens) - 1
    while i >= 0 and _blank(tokens[i]):
        i -= 1
    while i >= 0 and tokens[i].kind == "SQUARE_BLOCK":
        if i not in used:
            trailing.append(i)
        i -= 1
        while i >= 0 and _blank(tokens[i]):
            i -= 1
    trailing.reverse()

    languages: list[str] = []
    unclassified: list[str] = []
    translated: bool | None = None
    for position in trailing:
        used.add(position)
        value = tokens[position].content.strip()
        lang = _LANGUAGES.get(value.casefold())
        if lang:
            if lang[0] and lang[0] not in languages:
                languages.append(lang[0])
            if lang[1] is True:
                translated = True
            confidence["languages"] = 0.99
        else:
            unclassified.append(value)
            if value.casefold() in _EDITION or value.endswith(_GROUP_SUFFIXES):
                confidence["unclassified_tags"] = 0.87

    source: tuple[str, ...] = ()
    remaining = [i for i, token in enumerate(tokens) if i not in used and not _blank(token)]
    if remaining and tokens[remaining[-1]].kind == "ROUND_BLOCK":
        source_pos = remaining[-1]
        has_title_before = any(tokens[j].raw.strip() for j in remaining[:-1])
        if has_title_before:
            source = tuple(part.strip() for part in re.split(r"[,，、/]", tokens[source_pos].content) if part.strip())
            used.add(source_pos)
            confidence["source_works"] = 0.75

    title = "".join(token.raw for i, token in enumerate(tokens) if i not in used)
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        title = basename
        warnings.append("EMPTY_TITLE_AFTER_PARSE")
        overall = 0.0
        confidence["title"] = 0.0
    else:
        overall = sum(confidence.values()) / len(confidence)
        if warnings:
            overall *= 0.5

    return ParsedFilename(
        original_filename=original, basename=basename, extension=extension, event=event,
        creator_raw=creator, circle=circle, artists=artists, title=title, source_works=source,
        languages=tuple(languages), translated=translated, unclassified_tags=tuple(unclassified),
        parse_confidence=round(overall, 3), field_confidence=confidence,
        parse_warnings=tuple(dict.fromkeys(warnings)),
    )
