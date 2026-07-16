from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

from sqlalchemy import text

from dokura.metadata.database import WriteScheduler, create_database_engine
from dokura.metadata.migrations import upgrade_database


def test_initial_migration_and_required_connection_settings(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    upgrade_database(path)
    engine = create_database_engine(path)
    try:
        with engine.connect() as connection:
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert {"files", "pages", "tags", "file_tags", "tasks", "scans", "web_sessions", "cache_entries"} <= tables
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one().casefold() == "wal"
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert connection.execute(text("PRAGMA synchronous")).scalar_one() == 2
            assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 0
    finally:
        engine.dispose()


def test_write_scheduler_allows_only_one_transaction_at_a_time(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "writer.sqlite3")
    writer = WriteScheduler(engine)
    state_lock = Lock()
    active = 0
    maximum = 0

    def write() -> None:
        nonlocal active, maximum
        with writer.transaction():
            with state_lock:
                active += 1
                maximum = max(maximum, active)
            sleep(0.01)
            with state_lock:
                active -= 1

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _index: write(), range(8)))
        assert maximum == 1
    finally:
        engine.dispose()
