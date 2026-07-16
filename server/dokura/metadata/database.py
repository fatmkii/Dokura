from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool


def create_database_engine(path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{path}",
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=0,
        pool_timeout=5,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


class WriteScheduler:
    """Serializes the application's deliberately short SQLite write transactions."""

    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._lock = Lock()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self._lock, self._sessions.begin() as session:
            yield session

