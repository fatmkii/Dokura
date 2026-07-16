import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from dokura.constants import MINIMUM_SQLITE_VERSION


@dataclass(frozen=True, slots=True)
class SQLiteCapabilities:
    version: str
    fts5_trigram: bool


def _parse_version(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise RuntimeError(f"无法解析 SQLite 运行时版本: {version}") from exc


def verify_sqlite_capabilities(
    *,
    runtime_version: str | None = None,
    connect: Callable[[str], sqlite3.Connection] = sqlite3.connect,
) -> SQLiteCapabilities:
    version = runtime_version or sqlite3.sqlite_version
    required = ".".join(str(part) for part in MINIMUM_SQLITE_VERSION)
    if _parse_version(version) < MINIMUM_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite 运行时版本不满足要求: 当前 {version}，最低 {required}"
        )

    try:
        with connect(":memory:") as connection:
            connection.execute(
                "CREATE VIRTUAL TABLE dokura_fts_probe "
                "USING fts5(value, tokenize='trigram')"
            )
            connection.execute("INSERT INTO dokura_fts_probe(value) VALUES ('dokura')")
            matched = connection.execute(
                "SELECT count(*) FROM dokura_fts_probe WHERE value MATCH 'oku'"
            ).fetchone()[0]
            if matched != 1:
                raise RuntimeError("FTS5 trigram 自检查询未返回预期结果")
    except (sqlite3.Error, RuntimeError) as exc:
        raise RuntimeError(f"SQLite FTS5 trigram 不可用: {exc}") from exc

    return SQLiteCapabilities(version=version, fts5_trigram=True)
