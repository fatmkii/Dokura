import sqlite3

import pytest

from dokura.sqlite_check import verify_sqlite_capabilities


def test_accepts_required_sqlite_with_fts5_trigram() -> None:
    result = verify_sqlite_capabilities(runtime_version="3.51.3")
    assert result.version == "3.51.3"
    assert result.fts5_trigram is True


def test_rejects_old_sqlite_with_clear_reason() -> None:
    with pytest.raises(RuntimeError, match=r"当前 3\.50\.4，最低 3\.51\.3"):
        verify_sqlite_capabilities(runtime_version="3.50.4")


def test_rejects_missing_fts5_trigram_with_clear_reason() -> None:
    def broken_connect(_: str):
        raise sqlite3.OperationalError("no such tokenizer: trigram")

    with pytest.raises(RuntimeError, match="SQLite FTS5 trigram 不可用"):
        verify_sqlite_capabilities(runtime_version="3.51.3", connect=broken_connect)
