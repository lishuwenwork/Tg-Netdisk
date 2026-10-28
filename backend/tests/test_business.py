import asyncio
import base64
import io

import pytest
from PIL import Image

from tg_netdisk.core.config import AppError
from tg_netdisk.models.schemas import ConfirmResult, Draft, DraftItem, FrameRequest
from tg_netdisk.services.caption import compose, normalize_tags, utf16_length


def test_caption_plain_text_hashtags_and_utf16():
    text, entities = compose("😀 标题", "<b>原文</b>", ["4k", "#中文", "#4K"])
    assert text == "😀 标题\n\n<b>原文</b>\n\n#4k #中文"
    hashtag = next(e for e in entities if e["type"] == "hashtag")
    assert hashtag["offset"] == utf16_length(text[: text.index("#4k")])
    assert entities[0]["length"] == 5
    assert compose("", "", [])[0] == ""
    assert normalize_tags(["中文", "#中文"]) == ["#中文"]
    with pytest.raises(AppError):
        compose("😀" * 513, "", [])
    with pytest.raises(AppError):
        normalize_tags(["bad tag"])


def draft_for(asset, **kwargs):
    return Draft(
        channel_id="-1001234567890", title="First", items=[DraftItem(media_id=asset["id"])], **kwargs
    )


async def test_snapshot_is_immutable_and_single_video(services, video_asset):
    _, store, _, queue, gateway = services
    draft = draft_for(video_asset)
    task = await queue.enqueue(draft)
    draft.title = "Changed"
    draft.items.clear()
    await queue.execute(task)
    saved = await store.get("tasks", task["id"])
    assert saved["state"] == "succeeded"
    assert saved["snapshot"]["draft"]["title"] == "First"
    assert len(gateway.sent[0]["items"]) == 1
    assert saved["messages"][0]["media_id"] == video_asset["id"]


async def test_album_limits_order_and_random_ids(services, video_asset):
    _, store, _, queue, _ = services
    draft = draft_for(video_asset)
    draft.items *= 11
    with pytest.raises(AppError, match="10"):
        await queue.enqueue(draft)
    draft.items = draft.items[:10]
    task = await queue.enqueue(draft)
    ids = [i["random_id"] for i in task["snapshot"]["items"]]
    assert len(set(ids)) == 10
    await queue.cancel(task["id"])
    await queue.retry(task["id"])
    assert (await store.get("tasks", task["id"]))["snapshot"]["items"][0]["random_id"] == ids[0]


async def test_unknown_response_never_auto_retries(services, video_asset):
    _, store, _, queue, gateway = services
    task = await queue.enqueue(draft_for(video_asset))
    gateway.failure = TimeoutError("response lost after remote send")
    await queue.execute(task)
    assert (await store.get("tasks", task["id"]))["state"] == "unknown"
    assert len(gateway.sent) == 1
    with pytest.raises(AppError, match="待确认"):
        await queue.retry(task["id"])
    with pytest.raises(AppError):
        await queue.confirm(task["id"], ConfirmResult(outcome="failed", confirmed=False))
    await queue.confirm(task["id"], ConfirmResult(outcome="succeeded", confirmed=True, message_ids=[42]))
    assert (await store.get("tasks", task["id"]))["messages"][0]["message_id"] == 42


async def test_file_mutation_rejected_before_publish(services, video_asset):
    _, store, _, queue, gateway = services
    task = await queue.enqueue(draft_for(video_asset))
    from pathlib import Path

    Path(video_asset["path"]).write_bytes(b"changed")
    await queue.execute(task)
    saved = await store.get("tasks", task["id"])
    assert saved["state"] == "failed"
    assert "修改" in saved["error"]
    assert not gateway.sent


async def test_cancel_queued_is_not_published(services, video_asset):
    _, store, _, queue, gateway = services
    task = await queue.enqueue(draft_for(video_asset))
    await queue.cancel(task["id"])
    await queue.start()
    await asyncio.sleep(0.1)
    assert (await store.get("tasks", task["id"]))["state"] == "cancelled"
    assert not gateway.sent


async def test_restart_publishing_becomes_unknown(services, video_asset):
    _, store, _, queue, gateway = services
    task = await queue.enqueue(draft_for(video_asset))
    await store.patch("tasks", task["id"], state="publishing")
    await queue.start()
    await asyncio.sleep(0.05)
    assert (await store.get("tasks", task["id"]))["state"] == "unknown"
    assert not gateway.sent


async def test_cover_album_references_protect_frames_and_originals(services, video_asset):
    _, store, media, _, _ = services
    image = Image.new("RGB", (32, 24), "green")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    frame = await media.save_frame(
        FrameRequest(
            source_id=video_asset["id"],
            timestamp=0.5,
            image=base64.b64encode(buffer.getvalue()).decode(),
            purpose="cover",
        )
    )
    draft = draft_for(video_asset)
    draft.items[0].cover_id = frame["id"]
    await store.save("drafts", draft.model_dump())
    result = await media.cache(True)
    assert result["removed"] == 0
    assert (await media.get(frame["id"]))["path"]
    draft.items[0].cover_id = None
    await store.save("drafts", draft.model_dump())
    result = await media.cache(True)
    assert result["removed"] > 0
    from pathlib import Path

    assert Path(video_asset["path"]).is_file()


async def test_image_only_and_incomplete_media_rejected(services, video_asset):
    _, store, _, queue, _ = services
    await store.patch("media", video_asset["id"], status="downloading")
    with pytest.raises(AppError):
        await queue.enqueue(draft_for(video_asset))


async def test_database_roundtrip_and_ordered_items(services, video_asset):
    _, store, _, queue, _ = services
    draft = draft_for(video_asset)
    draft.items.append(DraftItem(media_id=video_asset["id"]))
    await store.save("drafts", draft.model_dump())
    restored = Draft.model_validate(await store.get("drafts", "current"))
    assert restored == draft
    task = await queue.enqueue(restored)
    from sqlalchemy import select

    from tg_netdisk.models.database import TaskItemRow

    rows = await store.run(lambda s: [(r.position, r.random_id) for r in s.scalars(select(TaskItemRow))])
    assert [r[0] for r in rows] == [0, 1]
    assert rows[1][1] == str(task["snapshot"]["items"][1]["random_id"])
