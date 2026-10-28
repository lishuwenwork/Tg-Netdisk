import asyncio
import hashlib
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from telethon import functions, types

from tg_netdisk.core.config import AppError

PART_SIZE = 512 * 1024
DEFAULT_CONCURRENCY = 4
MAX_IN_FLIGHT = 10
BIG_FILE_THRESHOLD = 10 * 1024 * 1024


async def upload_file(
    client,
    path: str,
    progress: Callable[[int, int], Awaitable[None]] | None = None,
    check_cancel: Callable[[], None] = lambda: None,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
):
    """Bounded MTProto part pipeline; only saves temporary bytes, never publishes messages."""
    source = Path(path)
    stat = await asyncio.to_thread(source.stat)
    size = stat.st_size
    if size <= 0:
        raise AppError("EMPTY_FILE", "文件为空")
    count = (size + PART_SIZE - 1) // PART_SIZE
    big = size > BIG_FILE_THRESHOLD
    file_id = secrets.randbits(63) or 1
    digest = hashlib.md5(usedforsecurity=False)
    pending: set[asyncio.Task] = set()
    progress_lock = asyncio.Lock()
    confirmed = 0
    latencies: list[float] = []
    started = time.monotonic()
    width = min(MAX_IN_FLIGHT, max(1, concurrency), count)

    async def save_part(index: int, chunk: bytes):
        nonlocal confirmed
        check_cancel()
        request = (
            functions.upload.SaveBigFilePartRequest(file_id, index, count, chunk)
            if big
            else functions.upload.SaveFilePartRequest(file_id, index, chunk)
        )
        before = time.monotonic()
        if not await client(request):
            raise AppError("UPLOAD_PART_FAILED", "服务器未确认上传分块，请重试", True)
        elapsed = time.monotonic() - before
        latencies.append(elapsed)
        check_cancel()
        async with progress_lock:
            confirmed += len(chunk)
            if progress:
                await progress(confirmed, size)

    try:
        with source.open("rb") as stream:
            for index in range(count):
                check_cancel()
                if len(pending) >= width:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    await asyncio.gather(*done)
                chunk = await asyncio.to_thread(stream.read, PART_SIZE)
                if len(chunk) != min(PART_SIZE, size - index * PART_SIZE):
                    raise AppError("FILE_CHANGED", "文件在上传时发生变化，请重新添加")
                if not big:
                    digest.update(chunk)
                pending.add(asyncio.create_task(save_part(index, chunk)))
            if pending:
                await asyncio.gather(*pending)
        current = await asyncio.to_thread(source.stat)
        if (current.st_size, current.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            raise AppError("FILE_CHANGED", "文件在上传时发生变化，请重新添加")
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    elapsed = max(time.monotonic() - started, 0.001)
    logging.getLogger("tg_netdisk").info(
        "upload_complete bytes=%d seconds=%.3f kib_s=%.1f part_kib=%d in_flight=%d mean_ack_ms=%.1f",
        size,
        elapsed,
        size / elapsed / 1024,
        PART_SIZE // 1024,
        width,
        sum(latencies) / max(1, len(latencies)) * 1000,
    )
    return (
        types.InputFileBig(file_id, count, source.name)
        if big
        else types.InputFile(file_id, count, source.name, digest.hexdigest())
    )
