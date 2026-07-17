from __future__ import annotations

import logging
import threading
import zipfile
from collections import deque
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from dokura.logging import RedactingFilter, RedactingFormatter


class DokuraLogHandler(logging.Handler):
    def __init__(self, log_dir: Path, max_bytes: int = 20 * 1024 * 1024, max_files: int = 10) -> None:
        super().__init__()
        self.log_dir = log_dir
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.write_error: str | None = None
        self._guard = threading.Lock()
        self._stream = None
        self._path: Path | None = None
        self._sequence = self._next_sequence()
        self._open_latest_or_new()

    def files(self) -> list[Path]:
        return sorted(self.log_dir.glob("dokura-*.log"))

    def _next_sequence(self) -> int:
        values = []
        for path in self.files():
            try:
                values.append(int(path.stem.rsplit("-", 1)[1]))
            except ValueError:
                continue
        return max(values, default=0) + 1

    def _new_path(self) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.log_dir / f"dokura-{stamp}-{self._sequence:06d}.log"
        self._sequence += 1
        return path

    def _open_latest_or_new(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            files = self.files()
            latest = files[-1] if files else None
            self._path = latest if latest and latest.stat().st_size < self.max_bytes else self._new_path()
            self._stream = self._path.open("a", encoding="utf-8")
            self.write_error = None
        except OSError as exc:
            self.write_error = str(exc)
            self._stream = None

    def _rotate(self) -> None:
        if self._stream is not None:
            self._stream.close()
        self._path = self._new_path()
        self._stream = self._path.open("a", encoding="utf-8")
        for path in self.files()[:-self.max_files]:
            try:
                path.unlink()
            except OSError:
                pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + "\n"
            encoded_size = len(message.encode("utf-8"))
            with self._guard:
                if self._stream is None:
                    self._open_latest_or_new()
                if self._stream is None or self._path is None:
                    return
                if self._path.stat().st_size and self._path.stat().st_size + encoded_size > self.max_bytes:
                    self._rotate()
                self._stream.write(message)
                self._stream.flush()
                self.write_error = None
        except OSError as exc:
            self.write_error = str(exc)

    def close(self) -> None:
        with self._guard:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        super().close()


class LogManager:
    def __init__(self, config_dir: Path, **handler_options) -> None:
        self.handler = DokuraLogHandler(config_dir / "logs", **handler_options)
        self.handler.addFilter(RedactingFilter())
        self.handler.setFormatter(
            RedactingFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        )

    def install(self) -> None:
        logging.getLogger().addHandler(self.handler)

    def read(self, levels: set[str] | None = None, limit: int = 1000) -> dict[str, object]:
        selected = {item.upper() for item in levels or set()}
        lines: deque[dict[str, str]] = deque(maxlen=limit)
        for path in self.handler.files():
            try:
                source = path.open("r", encoding="utf-8", errors="replace")
            except OSError:
                continue
            with source:
                for raw_line in source:
                    line = raw_line.rstrip("\n")
                    parts = line.split(" ", 3)
                    level = parts[2] if len(parts) > 2 else "INFO"
                    if selected and level not in selected:
                        continue
                    lines.append({"level": level, "message": line})
        return {"items": list(lines), "write_error": self.handler.write_error}

    def archive(self) -> bytes:
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self.handler.files():
                try:
                    with path.open("rb") as source, archive.open(path.name, "w") as target:
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                except OSError:
                    continue
        return output.getvalue()
