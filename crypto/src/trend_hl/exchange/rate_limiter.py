"""Token-bucket rate limiter, per endpoint class.

Hyperliquid imposes a global per-IP request budget plus per-endpoint weights.
We model it as multiple independent buckets keyed by ``category``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class Bucket:
    capacity: float
    tokens: float
    refill_per_s: float
    last_ts: float


class RateLimiter:
    def __init__(self, configs: dict[str, tuple[float, float]] | None = None) -> None:
        # category -> (capacity, refill_per_s)
        defaults = {
            "info": (1200.0, 1200.0 / 60.0),       # 1200/min reads
            "exchange": (60.0, 60.0 / 60.0),       # ~1 order/s sustained, burst 60
            "websocket": (1000.0, 1000.0 / 60.0),
        }
        configs = configs or defaults
        now = time.monotonic()
        self._buckets: dict[str, Bucket] = {
            k: Bucket(capacity=c, tokens=c, refill_per_s=r, last_ts=now)
            for k, (c, r) in configs.items()
        }
        self._lock = asyncio.Lock()

    async def acquire(self, category: str = "exchange", weight: float = 1.0) -> None:
        if category not in self._buckets:
            raise KeyError(f"unknown rate-limit category: {category}")
        while True:
            async with self._lock:
                b = self._buckets[category]
                now = time.monotonic()
                elapsed = now - b.last_ts
                b.tokens = min(b.capacity, b.tokens + elapsed * b.refill_per_s)
                b.last_ts = now
                if b.tokens >= weight:
                    b.tokens -= weight
                    return
                deficit = weight - b.tokens
                wait_s = deficit / b.refill_per_s if b.refill_per_s > 0 else 1.0
            await asyncio.sleep(min(wait_s, 5.0))
