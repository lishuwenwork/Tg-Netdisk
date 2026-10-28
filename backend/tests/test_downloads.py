import asyncio

import httpx

from tg_netdisk.models.schemas import DownloadRequest


async def test_download_rejects_html_without_creating_ready_asset(services, monkeypatch):
    _, store, media, _, _ = services
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, headers={"Content-Type": "text/html"}, text="<html>error page</html>")
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    asset = await media.start_download(DownloadRequest(url="https://example.com/video.mp4"))
    await asyncio.gather(*media.downloads.values())
    assert (await store.get("media", asset["id"]))["status"] == "failed"


async def test_download_content_sniff_and_completion(services, monkeypatch):
    _, store, media, _, _ = services
    content = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=content, headers={"Content-Type": "application/octet-stream"})
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    asset = await media.start_download(DownloadRequest(url="https://example.com/signed?secret=redacted"))
    assert asset["total"] is None
    assert "url" not in asset
    await asyncio.gather(*media.downloads.values())
    saved = await store.get("media", asset["id"])
    assert saved["status"] == "ready"
    assert saved["path"].endswith(".mp4")
    assert saved["size"] == len(content)
