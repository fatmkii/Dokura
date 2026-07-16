import unicodedata

import pytest

from dokura.metadata.filename_parser import parse_filename


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (
            "(C106) [きのこむ神 (きのこむし)] 永き夜の現に堕ちて (ブルーアーカイブ) [中国翻訳].zip",
            {"event": "C106", "circle": "きのこむ神", "artists": ("きのこむし",), "title": "永き夜の現に堕ちて", "source_works": ("ブルーアーカイブ",), "languages": ("zh",), "unclassified_tags": ()},
        ),
        (
            "(C106) [毛玉丸] シロコたちは先生の○○○が欲しい (ブルーアーカイブ) [中国翻訳] [欶澜汉化组].zip",
            {"circle": None, "artists": ("毛玉丸",), "title": "シロコたちは先生の○○○が欲しい", "unclassified_tags": ("欶澜汉化组",)},
        ),
        (
            "[ヴィヴィ堂 (クマ作民三)] ユウカとお泊まり 汗だくハメハメパーティ (ブルーアーカイブ) [中国翻訳] [DL版] [欶澜汉化组].zip",
            {"circle": "ヴィヴィ堂", "artists": ("クマ作民三",), "title": "ユウカとお泊まり 汗だくハメハメパーティ", "unclassified_tags": ("DL版", "欶澜汉化组")},
        ),
        (
            "[Breakthrough] 門主の一夢 (ブルーアーカイブ) [中国翻訳] [欶澜汉化组].zip",
            {"circle": "Breakthrough", "artists": (), "title": "門主の一夢"},
        ),
    ],
)
def test_documented_examples(filename: str, expected: dict[str, object]) -> None:
    parsed = parse_filename(filename)
    assert parsed.original_filename == filename
    assert parsed.translated is True
    assert not parsed.parse_warnings
    assert 0.7 <= parsed.parse_confidence <= 1
    for field, value in expected.items():
        assert getattr(parsed, field) == value


def test_full_width_brackets_unicode_nfc_and_case_preservation() -> None:
    original = "（C106）　［Circle （Artist）］ Cafe\u0301　Title （Series） ［English］.ZIP"
    parsed = parse_filename(original)
    assert parsed.original_filename == original
    assert parsed.basename == unicodedata.normalize("NFC", original[:-4])
    assert parsed.event == "C106"
    assert parsed.circle == "Circle"
    assert parsed.artists == ("Artist",)
    assert parsed.title == "Café Title"
    assert parsed.extension == "zip"


@pytest.mark.parametrize(
    ("filename", "title", "warnings"),
    [
        ("无任何括号的标题.zip", "无任何括号的标题", ()),
        ("[作者] 标题.zip", "标题", ()),
        ("[Circle (Artist)] Title (Part 2) (Series).zip", "Title (Part 2)", ()),
        ("Title [Unknown Tag].zip", "Title", ()),
        ("(C106 [Broken Bracket] Title.zip", "(C106 [Broken Bracket] Title", ("UNMATCHED_BRACKET",)),
        ("Title] Broken.zip", "Title] Broken", ("UNMATCHED_BRACKET",)),
        ("(C106) [作者].zip", "(C106) [作者]", ("EMPTY_TITLE_AFTER_PARSE",)),
    ],
)
def test_fallback_and_malformed_names(filename: str, title: str, warnings: tuple[str, ...]) -> None:
    parsed = parse_filename(filename)
    assert parsed.original_filename == filename
    assert parsed.title == title
    assert parsed.parse_warnings == warnings
    assert parsed.parse_confidence == (0 if "EMPTY_TITLE_AFTER_PARSE" in warnings else pytest.approx(parsed.parse_confidence))
