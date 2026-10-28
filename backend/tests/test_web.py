import base64
import io
from pathlib import Path

import pytest
from conftest import FakeGateway
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from tg_netdisk.api.app import create_app
from tg_netdisk.core.config import AppError, Config
from tg_netdisk.core.secrets import EncryptedSecretStore
from tg_netdisk.services.server_files import ServerFiles

PASSWORD = "web-test-password-123456"
ORIGIN = "https://workspace.example.test"


@pytest.fixture
def web_config(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "folder").mkdir()
    Image.new("RGB", (24, 16), "green").save(media / "封面 图片.png")
    (media / "folder/video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00")
    (media / "fake.mp4").write_text("not a real video")
    (media / "secret.txt").write_text("never list non-media")
    password = tmp_path / "web_password"
    password.write_text(PASSWORD)
    key = tmp_path / "key"
    key.write_bytes(Fernet.generate_key())
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>Web frontend</html>")
    return Config(
        mode="web",
        data_dir=tmp_path / "data",
        media_root=media,
        public_origin=ORIGIN,
        frontend_dir=frontend,
        web_password_file=password,
        secret_key_file=key,
    )


def login(client):
    response = client.post("/api/web/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    return response


def test_web_auth_cookie_origin_and_logout(web_config):
    app = create_app(web_config, gateway_factory=FakeGateway)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/health").json()["ready"]
        assert client.get("/api/snapshot").status_code == 401
        assert client.get("/api/media/unknown/file?token=" + web_config.token).status_code == 401
        assert client.get("/api/web/session").json()["authenticated"] is False
        assert client.post("/api/web/login", json={"password": PASSWORD}).status_code == 403
        response = login(client)
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
        assert client.get("/api/snapshot").status_code == 200
        assert (
            client.put(
                "/api/settings", json={"theme": "light"}, headers={"Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert client.put("/api/settings", json={"theme": "light"}).status_code == 403
        assert (
            client.put("/api/settings", json={"theme": "light"}, headers={"Origin": ORIGIN}).status_code
            == 200
        )
        assert client.post("/api/web/logout", headers={"Origin": ORIGIN}).status_code == 200
        assert client.get("/api/snapshot").status_code == 401


def test_web_limits_attempts_and_rejects_bad_websocket(web_config):
    with TestClient(create_app(web_config, gateway_factory=FakeGateway), base_url=ORIGIN) as client:
        with pytest.raises(WebSocketDisconnect) as failure:
            with client.websocket_connect("wss://workspace.example.test/api/events", headers={"Origin": ORIGIN}):
                pass
        assert failure.value.code == 4403
        for _ in range(5):
            assert (
                client.post(
                    "/api/web/login", json={"password": "wrong"}, headers={"Origin": ORIGIN}
                ).status_code
                == 401
            )
        assert (
            client.post("/api/web/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}).status_code
            == 429
        )


def test_web_browse_register_range_and_original_protection(web_config):
    with TestClient(create_app(web_config, gateway_factory=FakeGateway), base_url=ORIGIN) as client:
        login(client)
        headers = {"Origin": ORIGIN}
        listing = client.get("/api/server-files").json()
        assert listing["entries"][0]["directory"]
        assert "secret.txt" not in [e["name"] for e in listing["entries"]]
        images = client.get("/api/server-files?kind=image").json()["entries"]
        assert not any(e["path"] == "fake.mp4" for e in images)
        response = client.post(
            "/api/server-files/register", json={"paths": ["封面 图片.png"]}, headers=headers
        )
        asset = response.json()["assets"][0]
        assert asset["origin"] == "server"
        response = client.get(f"/api/media/{asset['id']}/file", headers={"Range": "bytes=0-9"})
        assert response.status_code == 206 and len(response.content) == 10
        assert (
            client.post(
                "/api/media/register",
                json={"paths": [str(web_config.media_root / "封面 图片.png")]},
                headers=headers,
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/downloads", json={"url": "https://example.com/video.mp4"}, headers=headers
            ).status_code
            == 400
        )
        assert client.post(
            "/api/server-files/register", json={"paths": ["fake.mp4"]}, headers=headers
        ).json()["failures"]
        result = client.post("/api/cache/clean", headers=headers).json()
        assert result["removed"] == 0 and (web_config.media_root / "封面 图片.png").exists()
        assert client.get("/api/server-files", params={"path": "../"}).status_code == 400
        assert client.post(
            "/api/server-files/register", json={"paths": ["../web_password"]}, headers=headers
        ).json()["failures"]


def test_server_path_guards_and_symlink_escape(web_config, tmp_path):
    files = ServerFiles(web_config.media_root)
    for value in ("../key", "/etc/passwd", "C:\\Windows\\file.png", "a\\..\\key", "x\x00y"):
        with pytest.raises(AppError):
            files.resolve(value)
    try:
        (web_config.media_root / "outside").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Creating a symlink is not permitted on this host")
    with pytest.raises(AppError):
        files.resolve("outside/key")


def test_web_encrypted_credentials_survive_restart_and_wrong_key_fails(web_config, tmp_path):
    web_config.prepare()
    first = EncryptedSecretStore(web_config.data_dir / "credentials.enc", web_config.secret_key_file)
    first.set("api_hash", "sensitive-value")
    assert b"sensitive-value" not in first.path.read_bytes()
    second = EncryptedSecretStore(first.path, web_config.secret_key_file)
    assert second.get("api_hash") == "sensitive-value"
    other = tmp_path / "other-key"
    other.write_bytes(Fernet.generate_key())
    with pytest.raises(AppError):
        EncryptedSecretStore(first.path, other)


def test_web_persists_draft_and_frames_without_browser(web_config):
    with TestClient(create_app(web_config, gateway_factory=FakeGateway), base_url=ORIGIN) as client:
        login(client)
        headers = {"Origin": ORIGIN}
        asset = client.post(
            "/api/server-files/register", json={"paths": ["folder/video.mp4"]}, headers=headers
        ).json()["assets"][0]
        metadata = {
            "duration": 2,
            "width": 640,
            "height": 360,
            "readable": True,
            "video_decodable": True,
            "audio_decodable": True,
        }
        assert (
            client.put(f"/api/media/{asset['id']}/metadata", json=metadata, headers=headers).status_code
            == 200
        )
        image = io.BytesIO()
        Image.new("RGB", (32, 24), "blue").save(image, format="PNG")
        frame = client.post(
            "/api/frames",
            json={
                "source_id": asset["id"],
                "timestamp": 0.5,
                "purpose": "cover",
                "image": base64.b64encode(image.getvalue()).decode(),
            },
            headers=headers,
        ).json()
        draft = {
            "title": "Web draft",
            "channel_id": "-100123",
            "items": [{"media_id": asset["id"], "cover_id": frame["id"]}],
        }
        assert client.put("/api/drafts/current", json=draft, headers=headers).status_code == 200
        task = client.post("/api/tasks", json=draft, headers=headers).json()
        import time

        for _ in range(100):
            result = client.get(f"/api/tasks/{task['id']}").json()
            if result["state"] == "succeeded":
                break
            time.sleep(0.01)
        assert result["state"] == "succeeded"
        old_cookie = client.cookies.get("tg_web_session")
    with TestClient(create_app(web_config, gateway_factory=FakeGateway), base_url=ORIGIN) as restarted:
        assert (
            restarted.get("/api/snapshot", headers={"Cookie": f"tg_web_session={old_cookie}"}).status_code
            == 401
        )
        login(restarted)
        snapshot = restarted.get("/api/snapshot").json()
        assert snapshot["draft"]["title"] == "Web draft"
        assert snapshot["tasks"][0]["state"] == "succeeded"
        assert Path(frame["path"]).is_file()
