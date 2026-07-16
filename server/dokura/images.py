from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from dokura.metadata.database import WriteScheduler
from dokura.metadata.analysis_service import FileSnapshot
from dokura.metadata.models import AnalysisStatus, File, Page
from dokura.metadata.zip_analyzer import MAX_DIMENSION, MAX_PIXELS, DeterministicPageError, TemporaryReadError, read_page


PREVIEW_SIZES = {256, 512, 768}
PREVIEW_CACHE_LIMIT = 128 * 1024 * 1024
GLOBAL_QUEUE_LIMIT = 64
CLIENT_QUEUE_LIMIT = 32


class ImageBusyError(Exception):
    pass


@dataclass(slots=True, eq=False)
class _Waiter:
    priority: int
    sequence: int
    client_id: str
    purpose: str


class ImageScheduler:
    """Bounded priority admission with one of three slots reserved for current pages."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._waiters: list[_Waiter] = []
        self._sequence = 0
        self._active = 0
        self._active_noncurrent = 0
        self.decode_slots = asyncio.Semaphore(2)

    @asynccontextmanager
    async def slot(self, purpose: str, client_id: str):
        await self.acquire(purpose, client_id)
        try:
            yield
        finally:
            await self.release(purpose)

    async def acquire(self, purpose: str, client_id: str) -> None:
        priorities = {"current": 0, "prefetch": 1, "preview": 2}
        async with self._condition:
            per_client = sum(item.client_id == client_id for item in self._waiters)
            if len(self._waiters) >= GLOBAL_QUEUE_LIMIT or per_client >= CLIENT_QUEUE_LIMIT:
                raise ImageBusyError
            self._sequence += 1
            waiter = _Waiter(priorities[purpose], self._sequence, client_id, purpose)
            self._waiters.append(waiter)
            try:
                while True:
                    first = min(self._waiters, key=lambda item: (item.priority, item.sequence))
                    allowed = self._active < 3 and (purpose == "current" or self._active_noncurrent < 2)
                    if first is waiter and allowed:
                        self._waiters.remove(waiter)
                        self._active += 1
                        if purpose != "current":
                            self._active_noncurrent += 1
                        break
                    await self._condition.wait()
            except BaseException:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                    self._condition.notify_all()
                raise
    async def release(self, purpose: str) -> None:
        async with self._condition:
            self._active -= 1
            if purpose != "current":
                self._active_noncurrent -= 1
            self._condition.notify_all()


@dataclass(slots=True)
class _InflightPreview:
    task: asyncio.Task[bytes]
    refs: int = 1


class PreviewCache:
    def __init__(self) -> None:
        self._items: OrderedDict[tuple[str, str, int, int], bytes] = OrderedDict()
        self._bytes = 0
        self._inflight: dict[tuple[str, str, int, int], _InflightPreview] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, key, factory) -> bytes:
        async with self._lock:
            cached = self._items.get(key)
            if cached is not None:
                self._items.move_to_end(key)
                return cached
            entry = self._inflight.get(key)
            if entry is None:
                task = asyncio.create_task(factory())
                entry = _InflightPreview(task)
                self._inflight[key] = entry
            else:
                task = entry.task
                entry.refs += 1
        try:
            result = await asyncio.shield(task)
        finally:
            async with self._lock:
                if task.done() and not task.cancelled() and task.exception() is None:
                    completed = task.result()
                    if key not in self._items and len(completed) <= PREVIEW_CACHE_LIMIT:
                        self._items[key] = completed
                        self._bytes += len(completed)
                        while self._bytes > PREVIEW_CACHE_LIMIT:
                            _old_key, old = self._items.popitem(last=False)
                            self._bytes -= len(old)
                entry.refs -= 1
                if entry.refs == 0:
                    self._inflight.pop(key, None)
                    if not task.done():
                        task.cancel()
        return result

    async def invalidate(self, file_id: str) -> None:
        async with self._lock:
            for key in [key for key in self._items if key[0] == file_id]:
                self._bytes -= len(self._items.pop(key))

    async def invalidate_stale(self, file_id: str, content_version: str) -> None:
        async with self._lock:
            for key in [key for key in self._items if key[0] == file_id and key[1] != content_version]:
                self._bytes -= len(self._items.pop(key))


@dataclass(frozen=True, slots=True)
class ImageRecord:
    file_id: str
    path: Path
    content_version: str
    page_number: int
    entry_name: str
    unavailable: bool
    unavailable_reason: str | None


class ImageService:
    def __init__(self, engine, writer: WriteScheduler, content_dir: Path, cover_dir: Path) -> None:
        self.engine = engine
        self.writer = writer
        self.content_dir = content_dir
        self.cover_dir = cover_dir
        self.scheduler = ImageScheduler()
        self.previews = PreviewCache()

    def page_record(self, file_id: str, page_number: int) -> ImageRecord | None:
        with Session(self.engine) as session:
            row = session.execute(
                select(File, Page).join(Page, Page.file_id == File.id).where(
                    File.id == file_id, File.present.is_(True), File.storage_unavailable.is_(False),
                    Page.page_number == page_number,
                )
            ).first()
            if row is None:
                return None
            item, page = row
            path = (self.content_dir / item.relative_path).resolve()
            root = self.content_dir.resolve()
            if not path.is_relative_to(root):
                return None
            try:
                if FileSnapshot.read(path).content_version != item.content_version:
                    raise TemporaryReadError("ZIP 内容版本已经变化")
            except OSError as exc:
                raise TemporaryReadError(str(exc)) from exc
            return ImageRecord(item.id, path, item.content_version, page.page_number, page.entry_name, page.unavailable, page.unavailable_reason)

    def cover_record(self, file_id: str) -> tuple[Path, str] | None:
        with Session(self.engine) as session:
            item = session.get(File, file_id)
            if item is None or not item.present or item.storage_unavailable or not item.cover_path:
                return None
            path = (self.cover_dir.parent / item.cover_path).resolve()
            root = self.cover_dir.parent.resolve()
            if not path.is_relative_to(root) or not path.is_file():
                return None
            return path, item.content_version

    async def preview(self, record: ImageRecord, size: int, client_id: str) -> bytes:
        key = (record.file_id, record.content_version, record.page_number, size)
        await self.previews.invalidate_stale(record.file_id, record.content_version)

        async def create() -> bytes:
            async with self.scheduler.slot("preview", client_id), self.scheduler.decode_slots:
                try:
                    return await asyncio.to_thread(self._render_preview, record, size)
                except DeterministicPageError as exc:
                    await asyncio.to_thread(self.mark_unavailable, record, exc.code)
                    raise

        return await self.previews.get_or_create(key, create)

    @staticmethod
    def _render_preview(record: ImageRecord, size: int) -> bytes:
        data = read_page(record.path, record.entry_name)
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, "JPEG", quality=80)
        return output.getvalue()

    def mark_unavailable(self, record: ImageRecord, reason: str) -> None:
        with self.writer.transaction() as session:
            page = session.scalar(select(Page).where(Page.file_id == record.file_id, Page.page_number == record.page_number))
            if page is None:
                return
            page.unavailable = True
            page.unavailable_reason = reason
            available = session.scalar(select(Page.id).where(Page.file_id == record.file_id, Page.unavailable.is_(False)).limit(1))
            if available is None:
                item = session.get(File, record.file_id)
                if item is not None:
                    item.status = AnalysisStatus.NO_VALID_CONTENT

    @staticmethod
    def validate_original_header(record: ImageRecord) -> None:
        try:
            with zipfile.ZipFile(record.path) as archive, archive.open(record.entry_name) as source:
                image = Image.open(source)
                width, height = image.size
                if image.format not in {"JPEG", "PNG"}:
                    raise DeterministicPageError("INVALID_IMAGE_FORMAT")
                if width <= 0 or height <= 0 or width > MAX_DIMENSION or height > MAX_DIMENSION:
                    raise DeterministicPageError("UNSAFE_IMAGE_DIMENSIONS")
                if width * height > MAX_PIXELS:
                    raise DeterministicPageError("IMAGE_PIXEL_LIMIT_EXCEEDED")
        except DeterministicPageError:
            raise
        except (UnidentifiedImageError, ValueError, Image.DecompressionBombError) as exc:
            raise DeterministicPageError("INVALID_IMAGE_DATA", str(exc)) from exc
        except KeyError as exc:
            raise TemporaryReadError("ZIP 内容可能已变化") from exc
        except zipfile.BadZipFile as exc:
            raise DeterministicPageError("CORRUPT_PAGE_DATA", str(exc)) from exc
        except OSError as exc:
            raise TemporaryReadError(str(exc)) from exc

    async def original_stream(self, record: ImageRecord, purpose: str, client_id: str, *, admitted: bool = False):
        if not admitted:
            await self.scheduler.acquire(purpose, client_id)
        try:
            archive = None
            source = None
            try:
                archive = await asyncio.to_thread(zipfile.ZipFile, record.path)
                try:
                    source = await asyncio.to_thread(archive.open, record.entry_name)
                except KeyError as exc:
                    raise TemporaryReadError("ZIP 内容可能已变化") from exc
                while chunk := await asyncio.to_thread(source.read, 1024 * 1024):
                    yield chunk
            except zipfile.BadZipFile:
                await asyncio.to_thread(self.mark_unavailable, record, "CORRUPT_PAGE_DATA")
                raise
            finally:
                if source is not None:
                    await asyncio.to_thread(source.close)
                if archive is not None:
                    await asyncio.to_thread(archive.close)
        finally:
            await self.scheduler.release(purpose)


def image_etag(*parts: object) -> str:
    return f'"{hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()}"'
