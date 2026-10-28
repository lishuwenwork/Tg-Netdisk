"""Create local-only UI fixtures; refuse to modify a normal user's data directory."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tg_netdisk.models.schemas import Draft, DraftItem
from tg_netdisk.repositories.store import Store
from tg_netdisk.services.media import fingerprint
from tg_netdisk.services.tasks import ACTIVE


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["seed", "finish"], required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    data_dir = args.data_dir.resolve()
    if not data_dir.is_relative_to((root / ".runtime").resolve()):
        parser.error(
            "UI fixtures are only allowed inside this project's .runtime directory"
        )
    store = Store(data_dir / "app.db")
    try:
        if args.mode == "finish":
            for task in await store.list("tasks"):
                if task["state"] in ACTIVE:
                    await store.patch("tasks", task["id"], state="cancelled")
            return
        source = data_dir.parent / "original.mp4"
        source.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00")
        asset = {
            "id": "fixture-media",
            "name": "original.mp4",
            "path": str(source),
            "kind": "video",
            "origin": "local",
            "status": "ready",
            "mime": "video/mp4",
            "metadata": {"readable": True, "video_decodable": True, "duration": 20},
            **fingerprint(source),
        }
        await store.save("media", asset)
        definitions = [
            ("upload", "uploading", "正在上传"),
            ("queued", "queued", "排队任务"),
            ("preparing", "preparing", "准备任务"),
            ("retry", "waiting_retry", "限流任务"),
            ("publishing", "publishing", "发布任务"),
            ("success", "succeeded", "已发布记录"),
            ("failed", "failed", "失败记录"),
            ("cancelled", "cancelled", "取消记录"),
            ("unknown", "unknown", "待确认记录"),
        ]
        for index, (key, state, title) in enumerate(definitions):
            stamp = datetime.now(UTC)
            draft = Draft(
                title=title,
                channel_id="-100123",
                items=[DraftItem(media_id=asset["id"])],
            )
            await store.save(
                "tasks",
                {
                    "id": f"fixture-{key}",
                    "state": state,
                    "created_at": (stamp - timedelta(seconds=index)).isoformat(),
                    "error": "",
                    "attempts": 0,
                    "snapshot": {
                        "draft": draft.model_dump(),
                        "caption": title,
                        "channel": {
                            "id": "-100123",
                            "name": "测试频道",
                            "can_post": True,
                        },
                        "items": [
                            {
                                "media_id": asset["id"],
                                "cover_id": None,
                                "asset": asset,
                                "cover": None,
                                "random_id": str(2**60 + index),
                            }
                        ],
                    },
                    "progress": {
                        "sent": 100000,
                        "total": 1000000,
                        "speed": 10000,
                        "item": 0,
                        "eta_seconds": 90,
                        "sampled_at": stamp.isoformat(),
                    },
                    "retry_in": 30,
                    "messages": [],
                },
            )
            messages = (
                [
                    {
                        "media_id": asset["id"],
                        "channel_id": "-100123",
                        "message_id": 100,
                        "grouped_id": "",
                    }
                ]
                if state == "succeeded"
                else []
            )
            await store.patch("tasks", f"fixture-{key}", state=state, messages=messages)
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
