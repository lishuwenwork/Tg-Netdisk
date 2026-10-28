import asyncio
from collections.abc import Awaitable, Callable

from tg_netdisk.repositories.store import now
from tg_netdisk.services.progress import UploadProgress


class ProgressReporter:
    """Coalesce UI/SQLite work outside the network ACK path, and drain before changing phase."""

    def __init__(self, sizes: list[int], emit: Callable[[dict], Awaitable[None]], interval: float = 0.5):
        self.tracker = UploadProgress(sizes)
        self.emit = emit
        self.interval = interval
        self.pending: dict[int, tuple[int, int]] = {}
        self.changed = asyncio.Event()
        self.stopping = asyncio.Event()
        self.closed = False
        self.worker = asyncio.create_task(self.run())

    async def progress(self, index: int, sent: int, total: int):
        if not self.closed:
            self.pending[index] = (sent, total)
            self.changed.set()

    async def run(self):
        while True:
            await self.changed.wait()
            self.changed.clear()
            pending, self.pending = self.pending, {}
            value = None
            for index, (sent, total) in sorted(pending.items()):
                value = self.tracker.update(index, sent, total)
            if value is not None:
                await self.emit({**value, "sampled_at": now()})
            if self.closed and not self.pending:
                return
            try:
                await asyncio.wait_for(self.stopping.wait(), self.interval)
            except TimeoutError:
                pass

    async def close(self):
        self.closed = True
        self.stopping.set()
        self.changed.set()
        await self.worker
