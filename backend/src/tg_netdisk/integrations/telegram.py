import asyncio
import base64
import inspect
import io
import logging
import secrets
import time
from datetime import UTC, datetime
from typing import NotRequired, TypedDict
from urllib.parse import unquote, urlsplit

import qrcode
from telethon import TelegramClient, errors, functions, types, utils

from tg_netdisk.core.config import AppError
from tg_netdisk.core.diagnostics import crypto_report
from tg_netdisk.integrations.uploader import DEFAULT_CONCURRENCY, upload_file


class AuthState(TypedDict):
    state: str
    user: dict | None
    caption_limit: int
    qr: NotRequired[str]
    expires: NotRequired[str]


class TelegramGateway:
    def __init__(self, config, store, events, secrets):
        self.config, self.store, self.events, self.secrets = config, store, events, secrets
        self.client: TelegramClient | None = None
        self.login_waiter: asyncio.Task | None = None
        self.auth: AuthState = {"state": "unconfigured", "user": None, "caption_limit": 1024}
        self.lock = asyncio.Lock()

    async def connect(self):
        async with self.lock:
            if self.client:
                if not self.client.is_connected():
                    await self.client.connect()
                return self.client
            settings = await self.store.get("settings", "app") or {}
            api_id, api_hash = settings.get("api_id", ""), self.secrets.get("api_hash")
            if not str(api_id).isdecimal() or not api_hash:
                raise AppError("API_REQUIRED", "请先保存 API ID 和 API Hash")
            proxy_url = self.secrets.get("telegram_proxy")
            proxy = None
            if proxy_url:
                parsed = urlsplit(proxy_url)
                if (
                    parsed.scheme not in ("socks5", "socks4", "http")
                    or not parsed.hostname
                    or not parsed.port
                ):
                    raise AppError("INVALID_PROXY", "Telegram 代理格式无效")
                proxy = {
                    "proxy_type": parsed.scheme,
                    "addr": parsed.hostname,
                    "port": parsed.port,
                    "username": unquote(parsed.username or ""),
                    "password": unquote(parsed.password or ""),
                    "rdns": True,
                }
            # No implicit final-send retries: the queue owns the uncertainty boundary.
            client = TelegramClient(
                str(self.config.data_dir / "telegram.session"),
                int(api_id),
                api_hash,
                proxy=proxy,
                request_retries=0,
                connection_retries=2,
                flood_sleep_threshold=0,
                raise_last_call_error=True,
                timeout=20,
            )
            await client.connect()
            self.client = client
            return client

    async def restore(self):
        try:
            client = await self.connect()
            if await client.is_user_authorized():
                await self._authorized()
            else:
                self.auth = {"state": "logged_out", "user": None, "caption_limit": 1024}
        except AppError:
            self.auth["state"] = "unconfigured"
        except (errors.AuthKeyUnregisteredError, errors.SessionRevokedError):
            self.auth["state"] = "logged_out"
        except Exception:
            self.auth["state"] = "offline"
        await self.events.emit("auth", **self.auth)

    async def _authorized(self):
        client = await self.connect()
        me = await client.get_me()
        limit = 1024
        try:
            config = await client(functions.help.GetAppConfigRequest(hash=0))
            if isinstance(config, types.help.AppConfig):
                values = {v.key: getattr(v.value, "value", None) for v in config.config.value}
                limit = int(
                    values.get(
                        "caption_length_limit_premium" if me.premium else "caption_length_limit_default", 1024
                    )
                    or 1024
                )
        except Exception:
            # Conservative API default until the account-specific server value is available.
            pass
        self.auth = {
            "state": "authorized",
            "user": {
                "id": str(me.id),
                "name": " ".join(filter(None, (me.first_name, me.last_name))),
                "premium": bool(me.premium),
            },
            "caption_limit": limit,
        }
        await self.channels()
        await self.events.emit("auth", **self.auth)

    async def qr(self):
        await self.cancel_login()
        client = await self.connect()
        qr = await client.qr_login()
        image = qrcode.make(qr.url)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.auth = {
            **self.auth,
            "state": "waiting_qr",
            "qr": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
            "expires": qr.expires.isoformat(),
        }

        async def wait():
            try:
                await qr.wait()
                await self._authorized()
            except errors.SessionPasswordNeededError:
                self.auth = {"state": "password_required", "user": None, "caption_limit": 1024}
            except asyncio.TimeoutError:
                self.auth = {"state": "qr_expired", "user": None, "caption_limit": 1024}
            except asyncio.CancelledError:
                return
            except Exception:
                self.auth = {"state": "offline", "user": None, "caption_limit": 1024}
            await self.events.emit("auth", **self.auth)

        self.login_waiter = asyncio.create_task(wait())
        return self.auth

    async def password(self, password: str):
        if self.auth["state"] != "password_required":
            raise AppError("LOGIN_STATE", "请先扫码登录")
        try:
            await (await self.connect()).sign_in(password=password)
            await self._authorized()
        except errors.PasswordHashInvalidError as exc:
            raise AppError("WRONG_PASSWORD", "两步验证密码错误") from exc
        return self.auth

    async def cancel_login(self):
        if self.login_waiter:
            self.login_waiter.cancel()
            await asyncio.gather(self.login_waiter, return_exceptions=True)
            self.login_waiter = None
        if self.auth["state"] in ("waiting_qr", "password_required", "qr_expired"):
            self.auth = {"state": "logged_out", "user": None, "caption_limit": 1024}

    async def logout(self):
        await self.cancel_login()
        if self.client:
            await self.client.log_out()
            self.client = None
        self.auth = {"state": "logged_out", "user": None, "caption_limit": 1024}
        await self.events.emit("auth", **self.auth)

    async def require_auth(self):
        client = await self.connect()
        if not await client.is_user_authorized():
            raise AppError("LOGIN_REQUIRED", "请先登录 Telegram")
        return client

    async def channels(self) -> list[dict]:
        client = await self.require_auth()
        result = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, types.Channel) and entity.broadcast:
                can_post = bool(entity.creator or (entity.admin_rights and entity.admin_rights.post_messages))
                channel = {
                    "id": str(utils.get_peer_id(entity)),
                    "name": dialog.name,
                    "can_post": can_post,
                    "checked_at": datetime.now(UTC).isoformat(),
                }
                await self.store.save("channels", channel)
                result.append(channel)
        return result

    async def resolve(self, channel_id: str) -> dict:
        client = await self.require_auth()
        text = channel_id.strip()
        if not text.lstrip("-").isdecimal():
            raise AppError("INVALID_CHANNEL", "请输入频道数字 ID")
        try:
            entity = await client.get_entity(int(text))
        except (ValueError, errors.ChannelPrivateError) as exc:
            raise AppError("CHANNEL_UNAVAILABLE", "未加入、实体未加载或频道不可访问，请刷新频道列表") from exc
        if not isinstance(entity, types.Channel) or not entity.broadcast:
            raise AppError("NOT_CHANNEL", "请选择广播频道")
        permission = await client.get_permissions(entity, "me")
        can_post = bool(permission.is_creator or (permission.is_admin and permission.post_messages))
        if not can_post:
            raise AppError("NO_POST_PERMISSION", "频道无发帖权限，请联系频道管理员")
        data = {
            "id": str(utils.get_peer_id(entity)),
            "name": entity.title,
            "can_post": True,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        await self.store.save("channels", data)
        return data

    async def _upload_concurrency(self) -> int:
        settings = await self.store.get("settings", "app") or {}
        return settings.get("upload_concurrency", DEFAULT_CONCURRENCY)

    async def _upload_file(self, client, path, progress=None, check_cancel=lambda: None):
        # Freeze the window for this file; subsequent files use the latest saved setting.
        concurrency = await self._upload_concurrency()
        return await upload_file(client, path, progress, check_cancel, concurrency=concurrency)

    async def prepare(self, snapshot: dict, progress, check_cancel):
        client = await self.require_auth()
        peer = await client.get_input_entity(int(snapshot["channel"]["id"]))
        prepared = []
        for index, item in enumerate(snapshot["items"]):
            check_cancel()
            asset = item["asset"]

            async def callback(sent, total, idx=index):
                check_cancel()
                await progress(idx, sent, total)

            if asset["kind"] == "image":
                from tg_netdisk.integrations.images import derivative

                image_path = self.config.data_dir / "cache/thumbnails" / f"{item['media_id']}-photo.jpg"
                await derivative(asset["path"], image_path)
                uploaded = await self._upload_file(client, str(image_path), callback, check_cancel)
                media = types.InputMediaUploadedPhoto(file=uploaded)
            else:
                uploaded = await self._upload_file(client, asset["path"], callback, check_cancel)
                metadata = asset["metadata"]
                attributes = [
                    types.DocumentAttributeFilename(asset["name"]),
                    types.DocumentAttributeVideo(
                        duration=metadata["duration"],
                        w=metadata["width"],
                        h=metadata["height"],
                        supports_streaming=metadata.get("container", "").lower() in ("mp4", "quicktime"),
                    ),
                ]
                options = {}
                if item.get("cover"):
                    from tg_netdisk.integrations.images import derivative

                    thumb = await derivative(
                        item["cover"]["path"],
                        self.config.data_dir / "cache/thumbnails" / f"{item['cover_id']}-thumb.jpg",
                        True,
                    )
                    cover = await derivative(
                        item["cover"]["path"],
                        self.config.data_dir / "cache/thumbnails" / f"{item['cover_id']}-cover.jpg",
                    )
                    if "video_cover" not in inspect.signature(types.InputMediaUploadedDocument).parameters:
                        raise AppError(
                            "COVER_UNSUPPORTED", "当前 API 层不支持独立封面，请保留图片并更新适配层"
                        )
                    options["thumb"] = await self._upload_file(client, thumb, check_cancel=check_cancel)
                    cover_upload = await self._upload_file(client, cover, check_cancel=check_cancel)
                    cover_result = await client(
                        functions.messages.UploadMediaRequest(
                            peer=peer, media=types.InputMediaUploadedPhoto(file=cover_upload)
                        )
                    )
                    options["video_cover"] = utils.get_input_photo(cover_result.photo)
                media = types.InputMediaUploadedDocument(
                    file=uploaded, mime_type=asset["mime"], attributes=attributes, **options
                )
            # UploadMedia prepares a server reference, and does not publish a message.
            check_cancel()
            result = await client(functions.messages.UploadMediaRequest(peer=peer, media=media))
            if asset["kind"] == "image":
                ready = types.InputMediaPhoto(id=utils.get_input_photo(result.photo))
            else:
                ready_options = {}
                if item.get("cover"):
                    if "video_cover" not in inspect.signature(types.InputMediaDocument).parameters:
                        raise AppError("COVER_UNSUPPORTED", "当前 API 层无法在发布时保留独立封面")
                    ready_options["video_cover"] = options["video_cover"]
                ready = types.InputMediaDocument(
                    id=utils.get_input_document(result.document), **ready_options
                )
            prepared.append(ready)
        return peer, prepared

    @staticmethod
    def entities(values):
        return [
            (types.MessageEntityBold if e["type"] == "bold" else types.MessageEntityHashtag)(
                offset=e["offset"], length=e["length"]
            )
            for e in values
        ]

    async def publish(self, snapshot: dict, prepared) -> list[dict]:
        client = await self.require_auth()
        peer, media = prepared
        entities = self.entities(snapshot["entities"])
        if len(media) == 1:
            request = functions.messages.SendMediaRequest(
                peer=peer,
                media=media[0],
                message=snapshot["caption"],
                entities=entities,
                random_id=int(snapshot["items"][0]["random_id"]),
            )
        else:
            request = functions.messages.SendMultiMediaRequest(
                peer=peer,
                multi_media=[
                    types.InputSingleMedia(
                        media=item,
                        random_id=int(snapshot["items"][i]["random_id"]),
                        message=snapshot["caption"] if i == 0 else "",
                        entities=entities if i == 0 else [],
                    )
                    for i, item in enumerate(media)
                ],
            )
        response = await client(request)
        updates = getattr(response, "updates", [])
        mapping = {u.random_id: u.id for u in updates if isinstance(u, types.UpdateMessageID)}
        messages = {
            u.message.id: u.message
            for u in updates
            if isinstance(u, (types.UpdateNewChannelMessage, types.UpdateNewMessage))
        }
        if any(int(item["random_id"]) not in mapping for item in snapshot["items"]):
            raise AppError("INCOMPLETE_RESPONSE", "发送响应缺少关联信息，请查看频道核对")
        return [
            {
                "media_id": item["media_id"],
                "message_id": mapping[int(item["random_id"])],
                "channel_id": snapshot["channel"]["id"],
                "grouped_id": str(
                    getattr(messages.get(mapping[int(item["random_id"])]), "grouped_id", "") or ""
                ),
            }
            for item in snapshot["items"]
        ]

    async def reconcile(self, snapshot: dict) -> list[dict]:
        # Matching text/time/file names alone is insufficient evidence of this logical operation.
        # MTProto random_id lookup isn't generally available after losing the update mapping.
        return []

    async def diagnostics(self) -> dict:
        concurrency = await self._upload_concurrency()
        report = await asyncio.to_thread(crypto_report, True, concurrency)
        report.update(
            connected=False,
            latency_ms=None,
            proxy_enabled=bool(self.secrets.get("telegram_proxy")),
            dc_id=self.client.session.dc_id if self.client else None,
        )
        if self.auth["state"] != "authorized" or not self.client or not self.client.is_connected():
            return report
        durations = []
        try:
            for _ in range(3):
                started = time.perf_counter()
                await asyncio.wait_for(self.client(functions.PingRequest(ping_id=secrets.randbits(63))), 5)
                durations.append((time.perf_counter() - started) * 1000)
            report.update(connected=True, latency_ms=round(sum(durations) / len(durations), 1))
        except Exception as exc:
            logging.getLogger("tg_netdisk").warning("upload_diagnostics_failed kind=%s", type(exc).__name__)
        return report

    async def shutdown(self):
        await self.cancel_login()
        if self.client:
            await self.client.disconnect()
            self.client = None
