"""Heartbeat task + Prometheus-style metrics surface."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from loguru import logger

from ..core.event_bus import EventBus


@dataclass
class Metrics:
    bars_seen: int = 0
    signals_emitted: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    fills_total: int = 0
    last_equity: Decimal = Decimal(0)
    high_watermark: Decimal = Decimal(0)
    max_drawdown_pct: float = 0.0
    realised_pnl: Decimal = Decimal(0)
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def update_equity(self, equity: Decimal) -> None:
        self.last_equity = equity
        if equity > self.high_watermark:
            self.high_watermark = equity
        if self.high_watermark > 0:
            dd = float((equity - self.high_watermark) / self.high_watermark * 100)
            if dd < self.max_drawdown_pct:
                self.max_drawdown_pct = dd


METRICS = Metrics()


async def heartbeat_loop(
    bus: EventBus,
    notifier,  # INotifier
    every_s: int = 300,
    stop_event: asyncio.Event | None = None,
) -> None:
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        try:
            msg = (
                f"[heartbeat] equity={METRICS.last_equity} "
                f"hwm={METRICS.high_watermark} dd={METRICS.max_drawdown_pct:.2f}% "
                f"bars={METRICS.bars_seen} sigs={METRICS.signals_emitted} "
                f"orders={METRICS.orders_submitted} fills={METRICS.fills_total}"
            )
            logger.info(msg)
            await notifier.send(msg, level="info")
            _ = bus  # bus reserved for future heartbeat events
        except Exception as e:
            logger.warning(f"heartbeat err: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=every_s)
        except asyncio.TimeoutError:
            pass
