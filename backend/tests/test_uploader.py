import asyncio
import hashlib
import os

import pytest
from telethon import functions, types

from tg_netdisk.core.config import AppError
from tg_netdisk.integrations.uploader import PART_SIZE, upload_file


class Client:
    def __init__(self, fail=None, hold=None, start_at=4):
        self.parts = {}
        self.requests = []
        self.active = 0
        self.maximum = 0
        self.fail = fail
        self.hold = hold
        self.start_at = start_at
        self.started = asyncio.Event()

    async def __call__(self, request):
        assert isinstance(
            request, (functions.upload.SaveFilePartRequest, functions.upload.SaveBigFilePartRequest)
        )
        self.requests.append(request)
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        if self.active == self.start_at:
            self.started.set()
        try:
            if self.hold:
                await self.hold.wait()
            await asyncio.sleep(0.002 * (4 - request.file_part % 4))
            if self.fail and request.file_part == 0:
                if isinstance(self.fail, Exception):
                    raise self.fail
                return False
            self.parts[request.file_part] = request.bytes
            return True
        finally:
            self.active -= 1


async def test_small_upload_is_bounded_complete_and_has_correct_checksum(tmp_path):
    payload = b"".join(bytes([index]) * PART_SIZE for index in range(6)) + b"last"
    source = tmp_path / "中文 clip.mp4"
    source.write_bytes(payload)
    release = asyncio.Event()
    client = Client(hold=release)
    progress = []

    async def callback(sent, total):
        progress.append((sent, total))

    upload = asyncio.create_task(upload_file(client, str(source), callback))
    await asyncio.wait_for(client.started.wait(), 2)
    release.set()
    result = await upload
    assert isinstance(result, types.InputFile)
    assert result.parts == 7 and result.name == source.name
    assert result.md5_checksum == hashlib.md5(payload, usedforsecurity=False).hexdigest()
    assert b"".join(client.parts[index] for index in range(7)) == payload
    assert 1 < client.maximum <= 4
    assert all(len(request.bytes) <= PART_SIZE for request in client.requests)
    assert len({request.file_id for request in client.requests}) == 1
    assert [sent for sent, _ in progress] == sorted(sent for sent, _ in progress)
    assert progress[-1] == (len(payload), len(payload))


async def test_large_file_uses_big_file_requests_without_loading_whole_file(tmp_path):
    source = tmp_path / "big.mp4"
    with source.open("wb") as stream:
        stream.seek(11 * 1024 * 1024)
        stream.write(b"x")
    client = Client()
    result = await upload_file(client, str(source))
    assert isinstance(result, types.InputFileBig)
    assert result.parts == 23
    assert all(isinstance(request, functions.upload.SaveBigFilePartRequest) for request in client.requests)
    assert sum(len(part) for part in client.parts.values()) == source.stat().st_size
    assert client.maximum <= 4


@pytest.mark.parametrize("failure", [True, ConnectionError("offline")])
async def test_failed_ack_cancels_other_parts_without_silent_retry(tmp_path, failure):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"a" * PART_SIZE * 8)
    client = Client(fail=failure)
    with pytest.raises((AppError, ConnectionError)):
        await upload_file(client, str(source))
    assert client.active == 0
    assert sum(request.file_part == 0 for request in client.requests) == 1


@pytest.mark.parametrize("concurrency", [1, 4, 10])
async def test_cancel_stops_all_in_flight_parts(tmp_path, concurrency):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"a" * PART_SIZE * 12)
    client = Client(hold=asyncio.Event(), start_at=concurrency)
    task = asyncio.create_task(upload_file(client, str(source), concurrency=concurrency))
    await asyncio.wait_for(client.started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.active == 0 and len(client.requests) == concurrency


@pytest.mark.parametrize("concurrency", [1, 4, 10])
async def test_configured_concurrency_is_used_and_all_parts_complete(tmp_path, concurrency):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"a" * PART_SIZE * 12)
    release = asyncio.Event()
    client = Client(hold=release, start_at=concurrency)
    task = asyncio.create_task(upload_file(client, str(source), concurrency=concurrency))
    try:
        await asyncio.wait_for(client.started.wait(), 2)
        assert len(client.requests) == concurrency
        assert client.maximum == concurrency
        release.set()
        await task
        assert len(client.parts) == 12 and client.active == 0
        assert client.maximum == concurrency
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_file_mutation_is_rejected_before_publication(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"a" * PART_SIZE * 4)
    client = Client()
    original = client.__class__.__call__

    class MutatingClient(Client):
        async def __call__(self, request):
            if request.file_part == 0:
                stamp = source.stat()
                os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000))
            return await original(self, request)

    with pytest.raises(AppError, match="变化"):
        await upload_file(MutatingClient(), str(source))
