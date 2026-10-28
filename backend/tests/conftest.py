import pytest

from tg_netdisk.core.config import Config
from tg_netdisk.repositories.store import Store
from tg_netdisk.services.events import EventBus
from tg_netdisk.services.media import MediaService
from tg_netdisk.services.tasks import TaskQueue


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name, "")

    def set(self, name, value):
        self.values[name] = value


class FakeGateway:
    def __init__(self, *_):
        self.auth = {"state": "authorized", "caption_limit": 1024, "user": None}
        self.sent = []
        self.failure = None

    async def restore(self):
        pass

    async def shutdown(self):
        pass

    async def resolve(self, channel_id):
        return {"id": channel_id, "name": "Test channel", "can_post": True}

    async def prepare(self, snapshot, progress, check_cancel):
        check_cancel()
        for index, item in enumerate(snapshot["items"]):
            await progress(index, item["asset"]["size"], item["asset"]["size"])
        return snapshot

    async def publish(self, snapshot, prepared):
        self.sent.append(snapshot)
        if self.failure:
            raise self.failure
        return [
            {
                "media_id": item["media_id"],
                "channel_id": snapshot["channel"]["id"],
                "message_id": i + 1,
                "grouped_id": "987",
            }
            for i, item in enumerate(snapshot["items"])
        ]


@pytest.fixture
async def services(tmp_path):
    config = Config(data_dir=tmp_path, token="test-runtime-token")
    config.prepare()
    store = Store(tmp_path / "app.db")
    await store.initialize()
    bus, secrets, gateway = EventBus(), MemorySecrets(), FakeGateway()
    media = MediaService(config, store, bus, secrets)
    queue = TaskQueue(store, media, gateway, bus)
    yield config, store, media, queue, gateway
    await queue.shutdown()
    await media.shutdown()
    await store.close()


@pytest.fixture
async def video_asset(services, tmp_path):
    _, store, media, _, _ = services
    path = tmp_path / "中文 video.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00")
    asset = await media.register(str(path))
    return await store.patch(
        "media",
        asset["id"],
        metadata={
            "duration": 2.0,
            "width": 640,
            "height": 360,
            "readable": True,
            "video_decodable": True,
            "audio_decodable": True,
            "container": "MP4",
        },
    )
