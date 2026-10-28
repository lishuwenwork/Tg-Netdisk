from conftest import FakeGateway, MemorySecrets
from fastapi.testclient import TestClient

from tg_netdisk.api.app import create_app
from tg_netdisk.core.config import Config


def test_auth_origin_range_and_path_isolation(tmp_path):
    from PIL import Image

    path = tmp_path / "测试 图片.png"
    Image.new("RGB", (20, 20), "red").save(path)
    config = Config(data_dir=tmp_path / "data", token="runtime-test-token")
    app = create_app(config, gateway_factory=FakeGateway, secrets=MemorySecrets())
    headers = {"Authorization": "Bearer runtime-test-token", "Origin": "app://bundle"}
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        assert (
            client.get("/api/health", headers={**headers, "Origin": "https://evil.test"}).status_code == 403
        )
        assert client.get("/api/health", headers=headers).json()["ready"]
        response = client.post("/api/media/register", headers=headers, json={"paths": [str(path)]})
        asset = response.json()["assets"][0]
        partial = client.get(f"/api/media/{asset['id']}/file", headers={**headers, "Range": "bytes=0-9"})
        assert partial.status_code == 206
        assert len(partial.content) == 10
        assert partial.headers["content-range"].startswith("bytes 0-9/")
        assert client.get("/api/media/not-registered/file", headers=headers).status_code == 400
        assert client.get("/api/media/%2E%2E%2Fsecret/file", headers=headers).status_code == 404
        value = client.get("/api/settings", headers=headers).json()
        assert "api_hash" not in value
        assert "telegram_proxy" not in value
        assert client.put("/api/settings", headers=headers, json={"api_id": "abc"}).status_code == 400


def test_history_delete_endpoint_is_authenticated_and_checks_live_state(tmp_path):
    config = Config(data_dir=tmp_path, token="runtime-test-token")
    app = create_app(config, gateway_factory=FakeGateway, secrets=MemorySecrets())
    headers = {"Authorization": "Bearer runtime-test-token"}
    with TestClient(app) as client:
        for task_id, state in [("finished", "succeeded"), ("uncertain", "unknown"), ("active", "uploading")]:
            client.portal.call(
                app.state.store.save,
                "tasks",
                {
                    "id": task_id,
                    "state": state,
                    "snapshot": {"items": []},
                    "created_at": "2026-10-27T00:00:00Z",
                },
            )
        assert client.delete("/api/tasks/finished").status_code == 401
        assert client.delete("/api/tasks/active", headers=headers).json()["code"] == "TASK_ACTIVE"
        assert (
            client.delete("/api/tasks/uncertain", headers=headers).json()["code"]
            == "UNKNOWN_CONFIRMATION_REQUIRED"
        )
        assert client.delete("/api/tasks/uncertain?confirm_unknown=true", headers=headers).json()["deleted"]
        assert client.delete("/api/tasks/finished", headers=headers).json()["deleted"]
        assert client.get("/api/tasks/finished", headers=headers).status_code == 404
        assert not client.delete("/api/tasks/finished", headers=headers).json()["deleted"]


def test_proxy_values_only_return_to_explicit_authenticated_editor(tmp_path):
    secrets = MemorySecrets()
    secrets.set("telegram_proxy", "socks5://example:pass@127.0.0.1:10808")
    secrets.set("download_proxy", "http://127.0.0.1:7890")
    secrets.set("api_hash", "a" * 32)
    app = create_app(
        Config(data_dir=tmp_path, token="runtime-test-token"), gateway_factory=FakeGateway, secrets=secrets
    )
    headers = {"Authorization": "Bearer runtime-test-token"}
    with TestClient(app) as client:
        assert client.get("/api/settings/proxies").status_code == 401
        values = client.get("/api/settings/proxies", headers=headers).json()
        assert values["telegram_proxy"] == secrets.get("telegram_proxy")
        assert values["download_proxy"] == secrets.get("download_proxy")
        assert "api_hash" not in values
        snapshot = client.get("/api/snapshot", headers=headers).json()
        assert "telegram_proxy" not in snapshot["settings"]
        assert "api_hash" not in snapshot["settings"]
        assert client.get("/api/health", headers=headers).json()["native_crypto"]


def test_upload_concurrency_defaults_validation_partial_save_and_restart(tmp_path):
    config = Config(data_dir=tmp_path, token="runtime-test-token")
    headers = {"Authorization": "Bearer runtime-test-token"}
    app = create_app(config, gateway_factory=FakeGateway, secrets=MemorySecrets())
    with TestClient(app) as client:
        assert client.get("/api/settings", headers=headers).json()["upload_concurrency"] == 4
        # Simulate a configuration written by a version without upload_concurrency.
        client.portal.call(app.state.store.save, "settings", {"id": "app", "api_id": "123", "theme": "light"})
        assert client.get("/api/snapshot", headers=headers).json()["settings"]["upload_concurrency"] == 4
        for invalid in [0, 11, -1, 1.5, 4.0, "4", True, None]:
            response = client.put("/api/settings", headers=headers, json={"upload_concurrency": invalid})
            assert response.status_code == 422
        for value in [1, 4, 10]:
            response = client.put("/api/settings", headers=headers, json={"upload_concurrency": value})
            assert response.status_code == 200
            data = response.json()
            assert data["upload_concurrency"] == value
            assert data["api_id"] == "123" and data["theme"] == "light"
        assert client.get("/api/health", headers=headers).json()["max_in_flight"] == 10
    restarted = create_app(config, gateway_factory=FakeGateway, secrets=MemorySecrets())
    with TestClient(restarted) as client:
        assert client.get("/api/settings", headers=headers).json()["upload_concurrency"] == 10


def test_concurrency_can_change_during_upload_without_reconnecting(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    app = create_app(
        Config(data_dir=tmp_path, token="runtime-test-token"),
        gateway_factory=FakeGateway,
        secrets=MemorySecrets(),
    )
    headers = {"Authorization": "Bearer runtime-test-token"}
    with TestClient(app) as client:
        client.get("/api/settings", headers=headers)
        shutdown = AsyncMock()
        monkeypatch.setattr(app.state.gateway, "shutdown", shutdown)
        app.state.queue.current = "active-upload"
        try:
            response = client.put("/api/settings", headers=headers, json={"upload_concurrency": 8})
            assert response.status_code == 200 and response.json()["upload_concurrency"] == 8
            shutdown.assert_not_awaited()
            blocked = client.put("/api/settings", headers=headers, json={"api_id": "456"})
            assert blocked.status_code == 400 and blocked.json()["code"] == "TASK_ACTIVE"
            assert client.get("/api/settings", headers=headers).json()["upload_concurrency"] == 8
        finally:
            app.state.queue.current = None
