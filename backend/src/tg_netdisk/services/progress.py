import math
import time
from collections import deque
from collections.abc import Callable


class UploadProgress:
    """Estimate transfer time from recent byte progress, independently for each attempt."""

    def __init__(self, sizes: list[int], clock: Callable[[], float] = time.monotonic):
        self.sizes = list(sizes)
        self.sent = [0] * len(sizes)
        self.clock = clock
        self.samples: deque[tuple[float, int]] = deque(maxlen=64)

    def initial(self) -> dict:
        return {
            "sent": 0,
            "total": sum(self.sizes),
            "speed": 0,
            "speed_ready": False,
            "item": 0,
            "eta_seconds": None,
        }

    def update(self, index: int, sent: int, total: int) -> dict:
        # Photos may be resized for Telegram; use their actual transmitted size once known.
        self.sizes[index] = max(0, total)
        self.sent[index] = max(0, min(sent, total))
        for previous in range(index):
            self.sent[previous] = self.sizes[previous]
        amount, overall, timestamp = sum(self.sent), sum(self.sizes), self.clock()
        if self.samples and amount < self.samples[-1][1]:
            self.samples.clear()
        self.samples.append((timestamp, amount))
        while len(self.samples) > 1 and timestamp - self.samples[0][0] > 8:
            self.samples.popleft()
        elapsed = timestamp - self.samples[0][0]
        speed = (amount - self.samples[0][1]) / elapsed if elapsed > 0 else 0.0
        remaining = max(0, overall - amount)
        reliable = len(self.samples) >= 3 and elapsed >= 2 and speed > 0 and remaining > 0
        return {
            "sent": amount,
            "total": overall,
            "speed": speed,
            "speed_ready": len(self.samples) >= 2 and elapsed > 0,
            "item": index,
            "eta_seconds": math.ceil(remaining / speed) if reliable else None,
        }
