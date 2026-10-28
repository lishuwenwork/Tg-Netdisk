import asyncio
from contextlib import asynccontextmanager

from tg_netdisk.repositories.store import now


class EventBus:
    def __init__(self):
        self.listeners: set[asyncio.Queue] = set()

    async def emit(self, event_type: str, entity_id: str = "", **data):
        event = {"type": event_type, "id": entity_id, "time": now(), "data": data}
        for queue in tuple(self.listeners):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        self.listeners.add(queue)
        try:
            yield queue
        finally:
            self.listeners.discard(queue)
