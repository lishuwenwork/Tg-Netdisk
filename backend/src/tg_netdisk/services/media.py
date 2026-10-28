import asyncio
import base64
import io
import mimetypes
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

from tg_netdisk.core.config import AppError
from tg_netdisk.repositories.store import now


def inspect_file(path: Path) -> dict:
    if not path.is_file():
        raise AppError("FILE_MISSING", "文件不存在，请重新选择")
    with path.open("rb") as stream:
        head = stream.read(64)
    stat = path.stat()
    if not stat.st_size:
        raise AppError("EMPTY_FILE", "文件为空")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            size = ImageOps.exif_transpose(image).size
            mime = Image.MIME.get(image.format or "", "image/jpeg")
        return {"kind": "image", "mime": mime, "width": size[0], "height": size[1]}
    except (OSError, ValueError, Image.DecompressionBombError):
        pass
    valid_video = (
        head[4:8] == b"ftyp"
        or head.startswith(b"\x1aE\xdf\xa3")
        or (head.startswith(b"RIFF") and head[8:12] == b"AVI ")
        or head.startswith((b"OggS", b"\x00\x00\x01"))
        or (head[4:8] in (b"moov", b"wide", b"mdat"))
    )
    if not valid_video:
        raise AppError("INVALID_MEDIA", "无法识别媒体内容，请选择有效的视频或图片")
    return {"kind": "video", "mime": mimetypes.guess_type(path.name)[0] or "video/mp4"}


def fingerprint(path: Path) -> dict:
    try:
        with path.open("rb"):
            stat = path.stat()
        return {"size": stat.st_size, "mtime_ns": str(stat.st_mtime_ns)}
    except OSError as exc:
        raise AppError("FILE_MISSING", "文件不可读，请重新选择") from exc


class MediaService:
    def __init__(self, config, store, events, secrets):
        self.config, self.store, self.events, self.secrets = config, store, events, secrets
        self.downloads: dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    async def restore(self):
        for asset in await self.store.list("media"):
            if asset["status"] == "ready":
                try:
                    await self.verify(asset)
                except AppError as exc:
                    await self.store.patch("media", asset["id"], status="failed", error=exc.message)

    async def register(self, path: str, origin: str = "local", asset_id: str | None = None) -> dict:
        source = Path(path).resolve()
        details = await asyncio.to_thread(inspect_file, source)
        fp = await asyncio.to_thread(fingerprint, source)
        data = {
            "id": asset_id or uuid.uuid4().hex,
            "name": source.name,
            "path": str(source),
            "origin": origin,
            "status": "ready",
            **fp,
            **details,
            "created_at": now(),
            "metadata": {"readable": details["kind"] == "image", "video_decodable": False, **details},
        }
        return await self.store.save("media", data)

    async def verify(self, asset: dict):
        if self.config.mode == "web":
            path = Path(asset["path"]).resolve()
            if asset.get("origin") == "server":
                allowed = path.is_relative_to(self.config.media_root.resolve())
            elif asset.get("origin") in ("frame", "thumbnail"):
                allowed = path.is_relative_to(
                    (self.config.data_dir / "media/frames").resolve()
                ) or path.is_relative_to((self.config.data_dir / "cache/thumbnails").resolve())
            else:
                allowed = False
            if not allowed:
                raise AppError("MEDIA_PATH_DENIED", "素材不在允许的服务器媒体目录中")
        fp = await asyncio.to_thread(fingerprint, Path(asset["path"]))
        if any(fp[k] != asset[k] for k in ("size", "mtime_ns")):
            raise AppError("FILE_CHANGED", f"文件已修改，请重新添加：{asset['name']}")
        if asset["status"] != "ready":
            raise AppError("MEDIA_NOT_READY", "素材尚未准备完成")

    async def get(self, asset_id: str) -> dict:
        data = await self.store.get("media", asset_id)
        if data is None:
            raise AppError("MEDIA_NOT_FOUND", "素材不存在")
        return data

    async def save_frame(self, request) -> dict:
        source = await self.get(request.source_id)
        await self.verify(source)
        if source["kind"] != "video" or not source.get("metadata", {}).get("video_decodable"):
            raise AppError("VIDEO_NOT_READY", "视频尚未通过解码检查")
        try:
            raw = base64.b64decode(request.image.split(",")[-1], validate=True)
        except ValueError as exc:
            raise AppError("INVALID_IMAGE", "图片数据无效") from exc
        asset_id = uuid.uuid4().hex
        folder = "cache/thumbnails" if request.purpose == "thumbnail" else "media/frames"
        path = self.config.data_dir / folder / f"{asset_id}.png"

        def save():
            if shutil.disk_usage(path.parent).free < len(raw) * 3 + 10_000_000:
                raise AppError("DISK_FULL", "磁盘空间不足，请清理后重试")
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    image.load()
                    ImageOps.exif_transpose(image).convert("RGB").save(path, "PNG")
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                raise AppError("INVALID_IMAGE", "截图无效") from exc

        async with self.lock:
            await asyncio.to_thread(save)
            asset = await self.register(
                str(path), "thumbnail" if request.purpose == "thumbnail" else "frame", asset_id
            )
            await self.store.save(
                "frames",
                {
                    "id": asset_id,
                    "source_id": source["id"],
                    "timestamp": request.timestamp,
                    "purpose": request.purpose,
                    "width": asset["width"],
                    "height": asset["height"],
                    "path": str(path),
                },
            )
        return asset

    async def start_download(self, request) -> dict:
        parsed = urlsplit(request.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
            raise AppError("INVALID_URL", "请输入 HTTP / HTTPS 视频直链")
        if any("\r" in k + v or "\n" in k + v for k, v in request.headers.items()):
            raise AppError("INVALID_HEADERS", "请求头格式无效")
        asset_id = uuid.uuid4().hex
        # Signed URLs and authentication headers live only inside the active coroutine.
        data = {
            "id": asset_id,
            "name": Path(parsed.path).name or "video",
            "origin": "download",
            "kind": "video",
            "status": "downloading",
            "size": 0,
            "downloaded": 0,
            "total": None,
            "speed": 0,
            "created_at": now(),
            "metadata": {},
        }
        await self.store.save("media", data)
        self.downloads[asset_id] = asyncio.create_task(self._download(asset_id, request))
        return data

    async def _download(self, asset_id: str, request):
        settings = await self.store.get("settings", "app") or {}
        directory = Path(settings.get("download_dir") or self.config.data_dir / "cache/downloads")
        directory.mkdir(parents=True, exist_ok=True)
        partial = directory / f"{asset_id}.part"
        started = time.monotonic()
        try:
            proxy = self.secrets.get("download_proxy") or None
            async with httpx.AsyncClient(
                proxy=proxy,
                follow_redirects=True,
                max_redirects=10,
                timeout=httpx.Timeout(45, connect=20),
                trust_env=False,
            ) as client:
                async with client.stream("GET", request.url, headers=request.headers) as response:
                    response.raise_for_status()
                    if "text/" in response.headers.get("content-type", "").lower():
                        raise AppError("NOT_VIDEO", "链接返回文本或网页，请使用视频文件直链")
                    length = response.headers.get("content-length", "")
                    total = int(length) if length.isdecimal() else None
                    if shutil.disk_usage(directory).free < (total or 100_000_000) + 50_000_000:
                        raise AppError("DISK_FULL", "下载目录空间不足")
                    received, last = 0, 0.0
                    with partial.open("wb") as stream:
                        async for chunk in response.aiter_bytes(512 * 1024):
                            await asyncio.to_thread(stream.write, chunk)
                            received += len(chunk)
                            current = time.monotonic()
                            if current - last > 0.4:
                                if shutil.disk_usage(directory).free < 20_000_000:
                                    raise AppError("DISK_FULL", "下载目录空间不足")
                                await self.store.patch(
                                    "media",
                                    asset_id,
                                    downloaded=received,
                                    total=total,
                                    speed=received / max(current - started, 0.01),
                                )
                                await self.events.emit("media", asset_id)
                                last = current
                    if total is not None and received != total:
                        raise AppError("DOWNLOAD_INCOMPLETE", "下载不完整，请重试", True)
            details = await asyncio.to_thread(inspect_file, partial)
            if details["kind"] != "video":
                raise AppError("NOT_VIDEO", "链接没有返回有效视频")
            ext = Path(urlsplit(request.url).path).suffix.lower()
            if ext not in (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".ogg"):
                with partial.open("rb") as stream:
                    ext = ".mp4" if stream.read(12)[4:8] == b"ftyp" else ".mkv"
            final = partial.with_suffix(ext)
            partial.rename(final)
            async with self.lock:
                await self.register(str(final), "download", asset_id)
            await self.events.emit("media", asset_id)
        except asyncio.CancelledError:
            await self.store.patch("media", asset_id, status="cancelled", error="下载已取消")
        except Exception as exc:
            message = exc.message if isinstance(exc, AppError) else "下载失败，请检查链接与下载代理"
            await self.store.patch("media", asset_id, status="failed", error=message)
        finally:
            partial.unlink(missing_ok=True)
            self.downloads.pop(asset_id, None)
            await self.events.emit("media", asset_id)

    async def cancel(self, asset_id: str):
        task = self.downloads.get(asset_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def references(self) -> set[str]:
        ids: set[str] = set()
        for draft in await self.store.list("drafts"):
            for item in draft.get("items", []):
                ids.update(filter(None, (item["media_id"], item.get("cover_id"))))
        for task in await self.store.list("tasks"):
            for item in task["snapshot"]["items"]:
                ids.update(filter(None, (item["media_id"], item.get("cover_id"))))
        for asset_id in list(ids):
            asset = await self.store.get("media", asset_id)
            if asset:
                ids.update(asset.get("metadata", {}).get("thumbnails", []))
        return ids

    async def cache(self, clean: bool = False) -> dict:
        async with self.lock:
            referenced = await self.references()
            reclaimable, protected, removed = 0, 0, 0
            assets = await self.store.list("media")
            registered_paths = {str(Path(a["path"]).resolve()).casefold() for a in assets if a.get("path")}
            for asset in assets:
                if asset.get("origin") in ("local", "server") or asset["status"] == "downloading":
                    continue
                path = Path(asset.get("path", ""))
                if not path.is_file():
                    continue
                size = path.stat().st_size
                if asset["id"] in referenced:
                    protected += size
                else:
                    reclaimable += size
                    if clean:
                        path.unlink()
                        removed += size
                        await self.store.remove("media", asset["id"])
                        await self.store.remove("frames", asset["id"])
            # Derived Telegram JPEGs and interrupted default-directory .part files have no media row.
            # Only walk directories owned by this application; never scan user source directories.
            for folder in ("cache/thumbnails", "cache/downloads", "media/frames"):
                root = (self.config.data_dir / folder).resolve()
                for path in root.iterdir():
                    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
                        continue
                    if str(path.resolve()).casefold() in registered_paths or path.stem in self.downloads:
                        continue
                    size = path.stat().st_size
                    owner = path.stem.split("-", 1)[0]
                    if owner in referenced:
                        protected += size
                    else:
                        reclaimable += size
                        if clean:
                            path.unlink()
                            removed += size
            return {"reclaimable": reclaimable, "protected": protected, "removed": removed}

    async def shutdown(self):
        for task in list(self.downloads.values()):
            task.cancel()
        await asyncio.gather(*self.downloads.values(), return_exceptions=True)
