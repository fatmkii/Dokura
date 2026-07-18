from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from watchfiles import Change, awatch

from dokura.metadata.scanning import ScanCoordinator


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EventWindow:
    duration: float = 1.0
    deadline: float | None = None
    events: dict[str, Change] = field(default_factory=dict)

    def add(self, changes: set[tuple[Change, str]], now: float) -> None:
        if changes and self.deadline is None:
            self.deadline = now + self.duration
        for change, path in changes:
            normalized = os.path.abspath(os.path.normpath(path))
            self.events[normalized] = change

    def pop_if_due(self, now: float) -> dict[str, Change] | None:
        if self.deadline is None or now < self.deadline:
            return None
        result = self.events
        self.events = {}
        self.deadline = None
        return result


async def watch_content(
    content_dir: Path, scans: ScanCoordinator, stop_event: asyncio.Event | None = None,
) -> None:
    """Watch recursively and retain only the latest event per normalized path each second."""
    window = EventWindow()
    unavailable = False
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        if not content_dir.is_dir():
            if not unavailable:
                logger.warning("Content 监听暂时不可用: %s", content_dir)
                scans.request_scan()
                unavailable = True
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1)
            except TimeoutError:
                pass
            continue
        if unavailable:
            scans.request_scan()
            unavailable = False
        try:
            async for changes in awatch(
                content_dir, debounce=100, step=50, rust_timeout=100,
                yield_on_timeout=True, recursive=True, stop_event=stop_event,
            ):
                now = monotonic()
                window.add(changes, now)
                merged = window.pop_if_due(now)
                if merged:
                    scans.request_scan()
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError):
            if not unavailable:
                logger.warning("Content 监听暂时不可用: %s", content_dir)
            if window.events:
                window.deadline = 0
                window.pop_if_due(monotonic())
            scans.request_scan()
            unavailable = True
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1)
            except TimeoutError:
                pass
