import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tg_netdisk import __version__
from tg_netdisk.core.config import AppError, Config
from tg_netdisk.core.diagnostics import crypto_report
from tg_netdisk.core.secrets import SecretStore
from tg_netdisk.integrations.telegram import TelegramGateway
from tg_netdisk.models.schemas import (
    ConfirmResult,
    ConnectionSettings,
    DownloadRequest,
    Draft,
    FrameRequest,
    Metadata,
    PasswordRequest,
    RegisterFiles,
    ResolveChannel,
)
from tg_netdisk.repositories.store import Store
from tg_netdisk.services.events import EventBus
from tg_netdisk.services.media import MediaService
from tg_netdisk.services.tasks import ACTIVE, TaskQueue


def create_app(config: Config | None = None, gateway_factory=TelegramGateway, secrets=None):
    config = config or Config()
    config.prepare()
    logging.getLogger("tg_netdisk").info("runtime version=%s upload=%s", __version__, crypto_report())
    store = Store(config.data_dir / "app.db")
    events = EventBus()
    secrets = secrets or SecretStore("Tg Netdisk " + str(config.data_dir))
    gateway = gateway_factory(config, store, events, secrets)
    media = MediaService(config, store, events, secrets)
    queue = TaskQueue(store, media, gateway, events)

    @asynccontextmanager
    async def lifespan(app):
        await store.initialize()
        await media.restore()
        await queue.start()
        restore = asyncio.create_task(gateway.restore())
        app.state.ready = True
        try:
            yield
        finally:
            restore.cancel()
            await asyncio.gather(restore, return_exceptions=True)
            await queue.shutdown()
            await media.shutdown()
            await gateway.shutdown()
            await store.close()

    app = FastAPI(
        title="Tg Netdisk",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store, app.state.queue, app.state.media = store, queue, media
    app.state.gateway, app.state.config = gateway, config
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "testserver"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.origins),
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Range"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in config.origins:
            return JSONResponse({"code": "ORIGIN_DENIED", "message": "来源未授权", "retryable": False}, 403)
        if request.method != "OPTIONS":
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            # Native media elements cannot add Authorization; access logs are disabled.
            if request.url.path.startswith("/api/media/") and request.url.path.endswith("/file"):
                token = token or request.query_params.get("token", "")
            if not hmac.compare_digest(token, config.token):
                return JSONResponse(
                    {"code": "UNAUTHORIZED", "message": "本地会话已失效", "retryable": False}, 401
                )
        try:
            return await call_next(request)
        except Exception:
            logging.getLogger("tg_netdisk").error("Request failed: %s %s", request.method, request.url.path)
            return JSONResponse(
                {"code": "INTERNAL", "message": "操作失败，请检查连接或日志", "retryable": False}, 500
            )

    @app.exception_handler(AppError)
    async def app_error(_, exc):
        return JSONResponse({"code": exc.code, "message": exc.message, "retryable": exc.retryable}, 400)

    @app.get("/api/health")
    async def health():
        settings = await store.get("settings", "app") or {}
        concurrency = settings.get("upload_concurrency", ConnectionSettings().upload_concurrency)
        return {
            "ready": getattr(app.state, "ready", False),
            "version": __version__,
            **crypto_report(concurrency=concurrency),
        }

    async def public_settings():
        data = {
            **ConnectionSettings().model_dump(exclude_none=True),
            **(await store.get("settings", "app") or {}),
        }
        return {
            **{k: v for k, v in data.items() if k not in ("api_hash", "telegram_proxy", "download_proxy")},
            "has_api_hash": bool(secrets.get("api_hash")),
            "has_telegram_proxy": bool(secrets.get("telegram_proxy")),
            "has_download_proxy": bool(secrets.get("download_proxy")),
            "data_dir": str(config.data_dir),
        }

    @app.get("/api/snapshot")
    async def snapshot():
        return {
            "settings": await public_settings(),
            "auth": gateway.auth,
            "draft": await store.get("drafts", "current") or Draft().model_dump(),
            "media": await store.list("media"),
            "channels": await store.list("channels"),
            "tasks": sorted(await store.list("tasks"), key=lambda t: t["created_at"], reverse=True),
        }

    @app.get("/api/settings")
    async def settings_get():
        return await public_settings()

    @app.get("/api/settings/proxies")
    async def settings_proxies():
        # Explicitly requested by the account editor; keep values out of broad snapshots and logs.
        return {
            "telegram_proxy": secrets.get("telegram_proxy"),
            "download_proxy": secrets.get("download_proxy"),
        }

    @app.get("/api/diagnostics/upload")
    async def upload_diagnostics():
        return await gateway.diagnostics()

    @app.put("/api/settings")
    async def settings_put(value: ConnectionSettings):
        secret_names = {"api_hash", "telegram_proxy", "download_proxy"}
        previous = {
            **ConnectionSettings().model_dump(exclude=secret_names),
            **(await store.get("settings", "app") or {}),
        }
        connection_changed = (
            "api_id" in value.model_fields_set and value.api_id != previous["api_id"]
        ) or any(
            getattr(value, name) is not None and getattr(value, name) != secrets.get(name)
            for name in secret_names
        )
        if queue.current and connection_changed:
            raise AppError("TASK_ACTIVE", "请等待当前任务结束后修改连接设置")
        if value.api_id and not value.api_id.isdecimal():
            raise AppError("INVALID_API_ID", "API ID 必须为正整数")
        if value.api_hash and (
            len(value.api_hash) != 32 or any(c not in "0123456789abcdefABCDEF" for c in value.api_hash)
        ):
            raise AppError("INVALID_API_HASH", "API Hash 应为 32 位十六进制字符")
        from urllib.parse import urlsplit

        for proxy in (value.telegram_proxy, value.download_proxy):
            if proxy and (
                urlsplit(proxy).scheme not in ("http", "https", "socks5", "socks4")
                or not urlsplit(proxy).hostname
            ):
                raise AppError("INVALID_PROXY", "代理格式无效")
        data = {**previous, **value.model_dump(exclude=secret_names, exclude_unset=True)}
        if value.default_channel and value.default_channel != previous["default_channel"]:
            channel = await gateway.resolve(value.default_channel)
            data["default_channel"] = channel["id"]
        for name in secret_names:
            secret = getattr(value, name)
            if secret is not None:
                secrets.set(name, secret)
        await store.save("settings", {"id": "app", **data})
        if connection_changed:
            await gateway.shutdown()
            await gateway.restore()
        return await public_settings()

    @app.post("/api/settings/test/{target}")
    async def connection_test(target: str):
        try:
            if target == "telegram":
                client = await gateway.connect()
                await asyncio.wait_for(client.get_me(), timeout=20)
            elif target == "download":
                async with httpx.AsyncClient(
                    proxy=secrets.get("download_proxy") or None, timeout=15, trust_env=False
                ) as client:
                    response = await client.get("https://example.com")
                    response.raise_for_status()
            else:
                raise AppError("INVALID_TARGET", "未知连接类型")
        except AppError:
            raise
        except Exception as exc:
            raise AppError("CONNECTION_FAILED", "连接失败，请检查网络与对应代理", True) from exc
        return {"ok": True}

    @app.get("/api/auth")
    async def auth_get():
        return gateway.auth

    @app.post("/api/auth/qr")
    async def auth_qr():
        return await gateway.qr()

    @app.post("/api/auth/password")
    async def auth_password(value: PasswordRequest):
        return await gateway.password(value.password)

    @app.post("/api/auth/cancel")
    async def auth_cancel():
        await gateway.cancel_login()
        return gateway.auth

    @app.post("/api/auth/logout")
    async def auth_logout():
        if queue.current:
            raise AppError("TASK_ACTIVE", "请先完成或取消当前任务")
        await gateway.logout()
        return gateway.auth

    @app.get("/api/channels")
    async def channel_list():
        return await store.list("channels")

    @app.post("/api/channels/refresh")
    async def channel_refresh():
        return await gateway.channels()

    @app.post("/api/channels/resolve")
    async def channel_resolve(value: ResolveChannel):
        return await gateway.resolve(value.channel_id)

    @app.post("/api/media/register")
    async def register(value: RegisterFiles):
        result, failures = [], []
        async with media.lock:
            for path in value.paths:
                try:
                    result.append(await media.register(path))
                except (AppError, OSError) as exc:
                    failures.append(
                        {
                            "name": Path(path).name,
                            "message": exc.message if isinstance(exc, AppError) else "文件不可读",
                        }
                    )
        return {"assets": result, "failures": failures}

    @app.put("/api/media/{asset_id}/metadata")
    async def metadata(asset_id: str, value: Metadata):
        await media.verify(await media.get(asset_id))
        return await store.patch("media", asset_id, metadata=value.model_dump())

    @app.get("/api/media/{asset_id}/file")
    async def media_file(asset_id: str):
        asset = await media.get(asset_id)
        await media.verify(asset)
        return FileResponse(asset["path"], media_type=asset["mime"], content_disposition_type="inline")

    @app.post("/api/downloads")
    async def download(value: DownloadRequest):
        return await media.start_download(value)

    @app.post("/api/downloads/{asset_id}/cancel")
    async def download_cancel(asset_id: str):
        await media.cancel(asset_id)
        return {"ok": True}

    @app.post("/api/frames")
    async def frames(value: FrameRequest):
        return await media.save_frame(value)

    @app.put("/api/drafts/current")
    async def save_draft(value: Draft):
        async with media.lock:
            return await store.save("drafts", {**value.model_dump(), "id": "current"})

    @app.post("/api/tasks")
    async def enqueue(value: Draft):
        return await queue.enqueue(value)

    @app.get("/api/tasks/{task_id}")
    async def task_get(task_id: str):
        task = await store.get("tasks", task_id)
        if not task:
            raise HTTPException(404)
        return {**task, "events": await store.events(task_id)}

    @app.post("/api/tasks/{task_id}/cancel")
    async def task_cancel(task_id: str):
        return await queue.cancel(task_id)

    @app.post("/api/tasks/{task_id}/retry")
    async def task_retry(task_id: str):
        return await queue.retry(task_id)

    @app.delete("/api/tasks/{task_id}")
    async def task_delete(task_id: str, confirm_unknown: bool = False):
        return await queue.delete(task_id, confirm_unknown)

    @app.post("/api/tasks/{task_id}/reconcile")
    async def task_reconcile(task_id: str):
        task = await store.get("tasks", task_id)
        if not task or task["state"] != "unknown":
            raise AppError("TASK_STATE", "任务无需核对")
        messages = await gateway.reconcile(task["snapshot"])
        if messages:
            return await queue.update(task_id, state="succeeded", messages=messages)
        return {"state": "unknown", "message": "缺少可证明的发送关联，请查看频道并人工核对"}

    @app.post("/api/tasks/{task_id}/confirm")
    async def task_confirm(task_id: str, value: ConfirmResult):
        return await queue.confirm(task_id, value)

    @app.get("/api/cache")
    async def cache_stats():
        return await media.cache()

    @app.post("/api/cache/clean")
    async def cache_clean():
        return await media.cache(True)

    @app.get("/api/status")
    async def status():
        return {
            "active": [t["id"] for t in await store.list("tasks") if t["state"] in ACTIVE],
            "downloads": list(media.downloads),
        }

    @app.websocket("/api/events")
    async def websocket(ws: WebSocket):
        if ws.headers.get("origin") not in config.origins or not hmac.compare_digest(
            ws.query_params.get("token", ""), config.token
        ):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            async with events.subscribe() as channel:
                await ws.send_json({"type": "connected", "id": "", "data": {}})
                while True:
                    try:
                        value = await asyncio.wait_for(channel.get(), timeout=20)
                    except asyncio.TimeoutError:
                        value = {"type": "heartbeat", "id": "", "data": {}}
                    await ws.send_json(value)
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app
