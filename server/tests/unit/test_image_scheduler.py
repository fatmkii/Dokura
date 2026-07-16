import asyncio

import pytest

import dokura.images as image_module
from dokura.images import CLIENT_QUEUE_LIMIT, GLOBAL_QUEUE_LIMIT, ImageBusyError, ImageScheduler, PreviewCache


def test_current_slot_is_reserved_and_cancelled_waiter_is_removed() -> None:
    async def scenario() -> None:
        scheduler = ImageScheduler()
        await scheduler.acquire("preview", "a")
        await scheduler.acquire("preview", "b")
        waiting = asyncio.create_task(scheduler.acquire("prefetch", "c"))
        await asyncio.sleep(0)
        current = asyncio.create_task(scheduler.acquire("current", "d"))
        await asyncio.wait_for(current, 1)
        assert scheduler._active == 3
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert not scheduler._waiters
        await scheduler.release("current")
        await scheduler.release("preview")
        await scheduler.release("preview")

    asyncio.run(scenario())


def test_per_client_queue_is_bounded() -> None:
    async def scenario() -> None:
        scheduler = ImageScheduler()
        await scheduler.acquire("preview", "active-a")
        await scheduler.acquire("preview", "active-b")
        await scheduler.acquire("current", "active-c")
        waiting = [asyncio.create_task(scheduler.acquire("preview", "same")) for _ in range(CLIENT_QUEUE_LIMIT)]
        await asyncio.sleep(0)
        with pytest.raises(ImageBusyError):
            await scheduler.acquire("preview", "same")
        for task in waiting:
            task.cancel()
        await asyncio.gather(*waiting, return_exceptions=True)
        assert not scheduler._waiters
        await scheduler.release("current")
        await scheduler.release("preview")
        await scheduler.release("preview")

    asyncio.run(scenario())


def test_global_queue_is_bounded_across_clients() -> None:
    async def scenario() -> None:
        scheduler = ImageScheduler()
        await scheduler.acquire("preview", "active-a")
        await scheduler.acquire("preview", "active-b")
        await scheduler.acquire("current", "active-c")
        waiting = [
            asyncio.create_task(scheduler.acquire("preview", f"client-{index // CLIENT_QUEUE_LIMIT}"))
            for index in range(GLOBAL_QUEUE_LIMIT)
        ]
        await asyncio.sleep(0)
        with pytest.raises(ImageBusyError):
            await scheduler.acquire("preview", "another-client")
        for task in waiting:
            task.cancel()
        await asyncio.gather(*waiting, return_exceptions=True)
        await scheduler.release("current")
        await scheduler.release("preview")
        await scheduler.release("preview")

    asyncio.run(scenario())


def test_concurrent_preview_work_is_merged() -> None:
    async def scenario() -> None:
        cache = PreviewCache()
        calls = 0

        async def factory() -> bytes:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return b"preview"

        results = await asyncio.gather(
            cache.get_or_create(("id", "v1", 1, 256), factory),
            cache.get_or_create(("id", "v1", 1, 256), factory),
        )
        assert results == [b"preview", b"preview"]
        assert calls == 1

    asyncio.run(scenario())


def test_preview_lru_obeys_byte_limit_and_cancels_orphaned_work(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(image_module, "PREVIEW_CACHE_LIMIT", 10)
        cache = PreviewCache()

        async def first() -> bytes:
            return b"12345678"

        async def second() -> bytes:
            return b"abcdefgh"

        await cache.get_or_create(("id", "v1", 1, 256), first)
        await cache.get_or_create(("id", "v1", 2, 256), second)
        assert list(cache._items) == [("id", "v1", 2, 256)]

        cancelled = asyncio.Event()

        async def blocked() -> bytes:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return b""

        request = asyncio.create_task(cache.get_or_create(("id", "v1", 3, 256), blocked))
        await asyncio.sleep(0)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        await asyncio.wait_for(cancelled.wait(), 1)
        assert ("id", "v1", 3, 256) not in cache._inflight

    asyncio.run(scenario())
