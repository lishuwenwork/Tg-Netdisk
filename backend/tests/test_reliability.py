import asyncio

import pytest
from PIL import Image
from telethon import errors

from tg_netdisk.models.schemas import Draft, DraftItem
from tg_netdisk.services.tasks import TaskQueue


def draft(asset):
    return Draft(channel_id="-100123", items=[DraftItem(media_id=asset["id"])])


async def test_cancel_after_send_boundary_is_unknown(services, video_asset):
    _, store, _, queue, gateway = services
    entered = asyncio.Event()

    async def publish(snapshot, prepared):
        entered.set()
        await asyncio.Event().wait()

    gateway.publish = publish
    task = await queue.enqueue(draft(video_asset))
    await queue.start()
    await asyncio.wait_for(entered.wait(), timeout=3)
    await queue.cancel(task["id"])
    assert (await store.get("tasks", task["id"]))["state"] == "unknown"


async def test_server_error_after_send_boundary_is_unknown(services, video_asset):
    _, store, _, queue, gateway = services
    gateway.failure = errors.ServerError(request=None, message="INTERNAL", code=500)
    task = await queue.enqueue(draft(video_asset))
    await queue.execute(task)
    assert (await store.get("tasks", task["id"]))["state"] == "unknown"
    assert len(gateway.sent) == 1


async def test_premium_upload_wait_is_not_treated_as_unknown_or_bypassed(services, video_asset, monkeypatch):
    _, store, _, queue, gateway = services
    original = gateway.prepare
    calls = 0
    waits = []

    async def prepare(snapshot, progress, check_cancel):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise errors.FloodPremiumWaitError(request=None, capture=1)
        return await original(snapshot, progress, check_cancel)

    original_sleep = asyncio.sleep

    async def sleep(seconds):
        waits.append(seconds)
        await original_sleep(0)

    gateway.prepare = prepare
    monkeypatch.setattr("tg_netdisk.services.tasks.asyncio.sleep", sleep)
    task = await queue.enqueue(draft(video_asset))
    await queue.execute(task)
    saved = await store.get("tasks", task["id"])
    assert saved["state"] == "succeeded"
    assert waits == [1] and calls == 2
    assert len(gateway.sent) == 1


async def test_two_queued_tasks_execute_serially(services, video_asset):
    _, store, media, _, gateway = services
    from tg_netdisk.services.events import EventBus

    queue = TaskQueue(store, media, gateway, EventBus())
    concurrent = 0
    maximum = 0
    original = gateway.publish

    async def publish(snapshot, prepared):
        nonlocal concurrent, maximum
        concurrent += 1
        maximum = max(maximum, concurrent)
        await asyncio.sleep(0.03)
        result = await original(snapshot, prepared)
        concurrent -= 1
        return result

    gateway.publish = publish
    tasks = [await queue.enqueue(draft(video_asset)), await queue.enqueue(draft(video_asset))]
    await queue.start()
    try:
        for _ in range(100):
            values = [await store.get("tasks", task["id"]) for task in tasks]
            if all(value["state"] == "succeeded" for value in values):
                break
            await asyncio.sleep(0.02)
        assert all(value["state"] == "succeeded" for value in values)
        assert maximum == 1
    finally:
        await queue.shutdown()


async def test_real_mixed_order_and_image_only_rejection(services, video_asset, tmp_path):
    _, store, media, queue, gateway = services
    path = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), "blue").save(path)
    photo = await media.register(str(path))
    value = Draft(
        channel_id="-100123",
        title="😀 album",
        tags=["#中文"],
        items=[
            DraftItem(media_id=photo["id"]),
            DraftItem(media_id=video_asset["id"]),
            DraftItem(media_id=photo["id"]),
        ],
    )
    task = await queue.enqueue(value)
    value.items.reverse()
    await queue.execute(task)
    result = await store.get("tasks", task["id"])
    assert [item["media_id"] for item in result["messages"]] == [photo["id"], video_asset["id"], photo["id"]]
    assert gateway.sent[0]["caption"] == "😀 album\n\n#中文"
    from tg_netdisk.core.config import AppError

    with pytest.raises(AppError, match="视频"):
        await queue.enqueue(Draft(channel_id="-100123", items=[DraftItem(media_id=photo["id"])]))


async def test_startup_validates_existing_file_fingerprint(services, video_asset):
    _, store, media, _, _ = services
    from pathlib import Path

    Path(video_asset["path"]).unlink()
    await media.restore()
    assert (await store.get("media", video_asset["id"]))["status"] == "failed"
