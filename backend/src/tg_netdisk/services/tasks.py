import asyncio
import copy
import logging
import secrets
import uuid

from telethon import errors

from tg_netdisk.core.config import AppError
from tg_netdisk.models.schemas import Draft
from tg_netdisk.repositories.store import now
from tg_netdisk.services.caption import compose
from tg_netdisk.services.progress import UploadProgress
from tg_netdisk.services.reporting import ProgressReporter

ACTIVE = {"queued", "preparing", "uploading", "publishing", "waiting_retry"}


class TaskQueue:
    def __init__(self, store, media, gateway, events):
        self.store, self.media, self.gateway, self.events = store, media, gateway, events
        self.wakeup = asyncio.Event()
        self.cancelled: set[str] = set()
        self.worker: asyncio.Task | None = None
        self.current: str | None = None
        self.execution: asyncio.Task | None = None
        self.action_lock = asyncio.Lock()

    async def start(self):
        for task in await self.store.list("tasks"):
            if task["state"] == "publishing":
                await self.update(task["id"], state="unknown", error="应用在发布阶段退出，请核对频道")
            elif task["state"] in ACTIVE - {"queued"}:
                await self.update(task["id"], state="failed", error="任务已中断，请检查后重试")
        for asset in await self.store.list("media"):
            if asset["status"] == "downloading":
                await self.store.patch("media", asset["id"], status="failed", error="下载已中断，请重新下载")
        self.worker = asyncio.create_task(self.loop())
        self.wakeup.set()

    async def update(self, task_id: str, **changes):
        value = await self.store.patch("tasks", task_id, **changes)
        await self.events.emit("task", task_id)
        return value

    async def snapshot(self, draft: Draft) -> dict:
        count = len(draft.items)
        if count < 1 or count > 10:
            raise AppError("ALBUM_COUNT", "请选择 1–10 项素材，超过 10 项请拆分")
        channel = await self.gateway.resolve(draft.channel_id)
        caption, entities = compose(
            draft.title,
            draft.description,
            draft.tags,
            draft.bold_title,
            self.gateway.auth.get("caption_limit", 1024),
        )
        items = []
        for item in draft.items:
            asset = await self.media.get(item.media_id)
            await self.media.verify(asset)
            if asset["kind"] == "video" and not asset.get("metadata", {}).get("video_decodable"):
                raise AppError("VIDEO_UNSUPPORTED", f"视频无法解码或尚未检查：{asset['name']}")
            cover = await self.media.get(item.cover_id) if item.cover_id else None
            if cover:
                await self.media.verify(cover)
                if cover["kind"] != "image" or asset["kind"] != "video":
                    raise AppError("INVALID_COVER", "视频封面必须是图片")
            items.append(
                {
                    **item.model_dump(),
                    "asset": asset,
                    "cover": cover,
                    "random_id": str(secrets.randbits(63) or 1),
                }
            )
        if not any(i["asset"]["kind"] == "video" for i in items):
            raise AppError("VIDEO_REQUIRED", "至少添加一个视频")
        return {
            "draft": draft.model_dump(),
            "channel": channel,
            "items": items,
            "caption": caption,
            "entities": entities,
        }

    async def enqueue(self, draft: Draft):
        async with self.media.lock:
            snapshot = await self.snapshot(draft)
            task = {
                "id": uuid.uuid4().hex,
                "snapshot": snapshot,
                "state": "queued",
                "created_at": now(),
                "progress": {
                    "sent": 0,
                    "total": sum(i["asset"]["size"] for i in snapshot["items"]),
                    "speed": 0,
                    "item": 0,
                },
                "error": "",
                "messages": [],
                "attempts": 0,
            }
            await self.store.save("tasks", task)
        self.wakeup.set()
        return task

    def check_cancel(self, task_id):
        if task_id in self.cancelled:
            raise asyncio.CancelledError

    async def cancel(self, task_id):
        async with self.action_lock:
            return await self._cancel(task_id)

    async def _cancel(self, task_id):
        task = await self.store.get("tasks", task_id)
        if not task or task["state"] not in ACTIVE:
            raise AppError("TASK_STATE", "当前任务不可取消")
        self.cancelled.add(task_id)
        if task_id == self.current and self.execution:
            self.execution.cancel()
            await asyncio.gather(self.execution, return_exceptions=True)
        elif task["state"] == "queued":
            await self.update(task_id, state="cancelled", error="已取消")
        return await self.store.get("tasks", task_id)

    async def retry(self, task_id):
        async with self.action_lock:
            return await self._retry(task_id)

    async def _retry(self, task_id):
        task = await self.store.get("tasks", task_id)
        if not task or task["state"] not in ("failed", "cancelled"):
            raise AppError("UNSAFE_RETRY", "结果待确认的任务需先核对频道，不能直接重试")
        self.cancelled.discard(task_id)
        progress = UploadProgress([item["asset"]["size"] for item in task["snapshot"]["items"]])
        await self.update(task_id, state="queued", error="", attempts=0, progress=progress.initial())
        self.wakeup.set()
        return await self.store.get("tasks", task_id)

    async def delete(self, task_id: str, confirm_unknown: bool = False) -> dict:
        async with self.action_lock:
            if task_id == self.current:
                raise AppError("TASK_ACTIVE", "任务仍在执行，请结束后再删除记录")
            deleted = await self.store.delete_task(task_id, confirm_unknown)
            self.cancelled.discard(task_id)
            await self.events.emit("task_deleted", task_id)
            return {"id": task_id, "deleted": deleted}

    async def loop(self):
        while True:
            await self.wakeup.wait()
            self.wakeup.clear()
            queued = sorted(
                (t for t in await self.store.list("tasks") if t["state"] == "queued"),
                key=lambda t: t["created_at"],
            )
            for task in queued:
                async with self.action_lock:
                    current = await self.store.get("tasks", task["id"])
                    if not current or current["state"] != "queued":
                        continue
                    self.current = task["id"]
                    self.execution = asyncio.create_task(self.execute(copy.deepcopy(current)))
                await asyncio.gather(self.execution, return_exceptions=True)
                self.execution, self.current = None, None

    async def execute(self, task):
        task_id, snapshot = task["id"], task["snapshot"]
        publishing = False
        try:
            for attempt in range(3):
                try:
                    self.check_cancel(task_id)
                    await self.update(task_id, state="preparing", attempts=attempt)
                    await self.gateway.resolve(snapshot["channel"]["id"])
                    for item in snapshot["items"]:
                        await self.media.verify(item["asset"])
                        if item.get("cover"):
                            await self.media.verify(item["cover"])
                    tracker = UploadProgress([item["asset"]["size"] for item in snapshot["items"]])
                    await self.update(task_id, state="uploading", progress=tracker.initial())

                    async def emit_progress(value):
                        await self.update(task_id, progress=value)

                    reporter = ProgressReporter(
                        [item["asset"]["size"] for item in snapshot["items"]], emit_progress
                    )
                    try:
                        prepared = await self.gateway.prepare(
                            snapshot, reporter.progress, lambda: self.check_cancel(task_id)
                        )
                    finally:
                        await reporter.close()
                    self.check_cancel(task_id)
                    await self.update(task_id, state="publishing", publish_started_at=now())
                    # Persist before crossing the network side-effect boundary.
                    publishing = True
                    messages = await self.gateway.publish(snapshot, prepared)
                    await self.update(
                        task_id, state="succeeded", messages=messages, error="", finished_at=now()
                    )
                    return
                except (errors.FloodWaitError, errors.FloodPremiumWaitError) as exc:
                    logging.getLogger("tg_netdisk").warning(
                        "upload_wait kind=%s seconds=%d", type(exc).__name__, exc.seconds
                    )
                    if publishing:
                        # Explicit RPC rejection means this request did not publish.
                        publishing = False
                    if attempt == 2:
                        raise AppError("FLOOD_WAIT", "限流重试次数已用完，请稍后重试") from exc
                    for remaining in range(exc.seconds, 0, -1):
                        self.check_cancel(task_id)
                        await self.update(
                            task_id,
                            state="waiting_retry",
                            retry_in=remaining,
                            error=f"Telegram 暂停上传，{remaining} 秒后重试",
                        )
                        await asyncio.sleep(1)
                except (ConnectionError, TimeoutError, OSError) as exc:
                    logging.getLogger("tg_netdisk").warning(
                        "upload_connection_retry kind=%s attempt=%d", type(exc).__name__, attempt + 1
                    )
                    if publishing or attempt == 2:
                        raise
                    await self.update(
                        task_id,
                        state="waiting_retry",
                        retry_in=2 ** (attempt + 1),
                        error="连接中断，等待重试",
                    )
                    await asyncio.sleep(2 ** (attempt + 1))
        except asyncio.CancelledError:
            await self.update(
                task_id,
                state="unknown" if publishing else "cancelled",
                error="发布已开始，请核对频道" if publishing else "已取消",
            )
        except errors.RPCError as exc:
            rejected = isinstance(
                exc, (errors.BadRequestError, errors.ForbiddenError, errors.UnauthorizedError)
            )
            duplicate = type(exc).__name__ == "RandomIdDuplicateError"
            uncertain = publishing and (not rejected or duplicate)
            await self.update(
                task_id,
                state="unknown" if uncertain else "failed",
                error=f"Telegram 返回：{type(exc).__name__}",
            )
        except Exception as exc:
            message = exc.message if isinstance(exc, AppError) else "连接或处理失败，请检查网络和素材"
            await self.update(task_id, state="unknown" if publishing else "failed", error=message)

    async def confirm(self, task_id, request):
        async with self.action_lock:
            return await self._confirm(task_id, request)

    async def _confirm(self, task_id, request):
        task = await self.store.get("tasks", task_id)
        if not task or task["state"] != "unknown":
            raise AppError("TASK_STATE", "仅待确认任务可核对结果")
        if not request.confirmed:
            raise AppError("CONFIRM_REQUIRED", "请先在频道核对发布结果")
        if request.outcome == "succeeded" and len(request.message_ids) != len(task["snapshot"]["items"]):
            raise AppError("MESSAGE_IDS_REQUIRED", "请按素材顺序填写所有消息 ID")
        messages = [
            {
                "media_id": item["media_id"],
                "message_id": mid,
                "channel_id": task["snapshot"]["channel"]["id"],
                "grouped_id": "",
            }
            for item, mid in zip(task["snapshot"]["items"], request.message_ids)
        ]
        return await self.update(
            task_id, state=request.outcome, messages=messages, error="人工核对结果", manually_confirmed=True
        )

    async def shutdown(self):
        if self.execution:
            self.execution.cancel()
            await asyncio.gather(self.execution, return_exceptions=True)
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
