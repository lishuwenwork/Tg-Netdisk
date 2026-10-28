import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from tg_netdisk.core.config import AppError
from tg_netdisk.models.database import TaskEvent, TaskItemRow, TaskMessage
from tg_netdisk.models.schemas import Draft, DraftItem


async def task_for(queue, asset):
    return await queue.enqueue(Draft(channel_id="-100123", items=[DraftItem(media_id=asset["id"])]))


async def test_history_deletion_removes_related_rows_and_preserves_files_and_draft(services, video_asset):
    _, store, media, queue, gateway = services
    value = Draft(channel_id="-100123", items=[DraftItem(media_id=video_asset["id"])])
    await store.save("drafts", value.model_dump())
    task = await queue.enqueue(value)
    await queue.execute(task)
    assert await store.events(task["id"])
    sent = len(gateway.sent)
    result = await queue.delete(task["id"])
    assert result["deleted"]
    assert await store.get("tasks", task["id"]) is None
    for table in (TaskItemRow, TaskMessage, TaskEvent):
        count = await store.run(lambda session: session.scalar(select(func.count()).select_from(table)))
        assert count == 0
    assert await store.get("drafts", "current") == value.model_dump()
    assert (await media.get(video_asset["id"]))["path"] == video_asset["path"]
    assert Path(video_asset["path"]).exists()
    assert len(gateway.sent) == sent
    assert not (await queue.delete(task["id"]))["deleted"]


@pytest.mark.parametrize("state", ["failed", "cancelled"])
async def test_failed_and_cancelled_history_can_be_deleted(services, video_asset, state):
    _, store, _, queue, _ = services
    task = await task_for(queue, video_asset)
    await store.patch("tasks", task["id"], state=state)
    assert (await queue.delete(task["id"]))["deleted"]


@pytest.mark.parametrize("state", ["queued", "preparing", "uploading", "publishing", "waiting_retry"])
async def test_active_tasks_cannot_be_deleted(services, video_asset, state):
    _, store, _, queue, _ = services
    task = await task_for(queue, video_asset)
    await store.patch("tasks", task["id"], state=state)
    with pytest.raises(AppError, match="不能删除"):
        await queue.delete(task["id"])
    assert await store.get("tasks", task["id"])


async def test_unknown_history_needs_explicit_confirmation(services, video_asset):
    _, store, _, queue, _ = services
    task = await task_for(queue, video_asset)
    await store.patch("tasks", task["id"], state="unknown")
    with pytest.raises(AppError) as failure:
        await queue.delete(task["id"])
    assert failure.value.code == "UNKNOWN_CONFIRMATION_REQUIRED"
    assert await store.get("tasks", task["id"])
    assert (await queue.delete(task["id"], confirm_unknown=True))["deleted"]


async def test_retry_and_delete_are_serialized(services, video_asset):
    _, store, _, queue, _ = services
    task = await task_for(queue, video_asset)
    await store.patch("tasks", task["id"], state="failed")
    outcomes = await asyncio.gather(queue.retry(task["id"]), queue.delete(task["id"]), return_exceptions=True)
    assert any(isinstance(value, AppError) for value in outcomes)
    assert not any(isinstance(value, KeyError) for value in outcomes)
    remaining = await store.get("tasks", task["id"])
    assert remaining is None or remaining["state"] == "queued"


async def test_current_execution_cannot_be_deleted_even_while_finishing(services, video_asset):
    _, store, _, queue, _ = services
    task = await task_for(queue, video_asset)
    await store.patch("tasks", task["id"], state="succeeded")
    queue.current = task["id"]
    with pytest.raises(AppError):
        await queue.delete(task["id"])
    queue.current = None
