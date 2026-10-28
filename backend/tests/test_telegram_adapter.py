from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telethon import functions, types

from tg_netdisk.integrations.telegram import TelegramGateway


async def test_album_low_level_request_keeps_order_caption_and_random_ids():
    adapter = TelegramGateway(None, None, None, None)
    requests = []

    class Client:
        async def __call__(self, request):
            requests.append(request)
            updates = []
            for i, item in enumerate(request.multi_media):
                updates.append(types.UpdateMessageID(id=i + 10, random_id=item.random_id))
                message = types.Message(
                    id=i + 10,
                    peer_id=types.PeerChannel(123),
                    date=datetime.now(UTC),
                    message=item.message,
                    grouped_id=98765,
                )
                updates.append(types.UpdateNewChannelMessage(message=message, pts=i + 1, pts_count=1))
            return SimpleNamespace(updates=updates)

    async def require():
        return Client()

    adapter.require_auth = require
    media = [
        types.InputMediaPhoto(id=types.InputPhoto(id=i, access_hash=i, file_reference=b"test"))
        for i in [3, 1, 2]
    ]
    snapshot = {
        "channel": {"id": "-100123"},
        "caption": "😀 #4k",
        "entities": [{"type": "hashtag", "offset": 3, "length": 3}],
        "items": [{"media_id": str(i), "random_id": str(2**60 + i)} for i in [3, 1, 2]],
    }
    result = await adapter.publish(snapshot, (types.InputPeerChannel(channel_id=123, access_hash=456), media))
    request = requests[0]
    assert isinstance(request, functions.messages.SendMultiMediaRequest)
    assert [item.message for item in request.multi_media] == ["😀 #4k", "", ""]
    assert [item.random_id for item in request.multi_media] == [2**60 + i for i in [3, 1, 2]]
    assert [item["media_id"] for item in result] == ["3", "1", "2"]
    assert [item["message_id"] for item in result] == [10, 11, 12]
    assert result[0]["grouped_id"] == "98765"


async def test_upload_diagnostics_uses_only_pings_and_never_exposes_credentials():
    from conftest import MemorySecrets

    secrets = MemorySecrets()
    secrets.set("telegram_proxy", "socks5://user:password@127.0.0.1:10808")
    adapter = TelegramGateway(
        None, SimpleNamespace(get=AsyncMock(return_value={"upload_concurrency": 8})), None, secrets
    )
    requests = []

    class Client:
        session = SimpleNamespace(dc_id=2)

        def is_connected(self):
            return True

        async def __call__(self, request):
            requests.append(request)
            assert isinstance(request, functions.PingRequest)
            return types.Pong(msg_id=1, ping_id=request.ping_id)

    adapter.client = Client()
    adapter.auth["state"] = "authorized"
    report = await adapter.diagnostics()
    assert report["crypto_backend"] == "cryptg" and report["native_crypto"]
    assert report["connected"] and report["latency_ms"] is not None
    assert report["max_in_flight"] == 8
    assert len(requests) == 3
    assert "password" not in str(report) and "127.0.0.1" not in str(report)


async def test_upload_reads_saved_concurrency_at_each_file_boundary(services, tmp_path, monkeypatch):
    import asyncio

    from tg_netdisk.integrations import telegram

    _, store, _, _, _ = services
    adapter = TelegramGateway(None, store, None, None)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def upload(client, path, progress, check_cancel, *, concurrency):
        calls.append(concurrency)
        started.set()
        await release.wait()
        return concurrency

    monkeypatch.setattr(telegram, "upload_file", upload)
    release.set()
    assert await adapter._upload_file(None, "old-config.mp4") == 4
    await store.save("settings", {"id": "app", "upload_concurrency": 1})
    assert await adapter._upload_file(None, "serial.mp4") == 1
    await store.save("settings", {"id": "app", "upload_concurrency": 8})
    started.clear()
    release.clear()
    current = asyncio.create_task(adapter._upload_file(None, "current.mp4"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        await store.patch("settings", "app", upload_concurrency=10)
        release.set()
        assert await current == 8
        assert await adapter._upload_file(None, "next.mp4") == 10
        assert calls == [4, 1, 8, 10]
    finally:
        current.cancel()
        await asyncio.gather(current, return_exceptions=True)
