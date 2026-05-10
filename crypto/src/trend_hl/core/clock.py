"""UTC clock with NTP drift detection.

Trading systems on EVM-style L1s reject signed payloads with stale or future
nonces. We monotonically derive nonces from a clock anchored to UTC and
periodically estimate offset against ``time.google.com`` (or pool.ntp.org).
If absolute drift exceeds ``MAX_DRIFT_MS`` we flip a ``drift_alarm`` flag the
executor watches before each order.

This module is dependency-free (uses ``ntplib`` lazily if installed; otherwise
falls back to disabling NTP checks but warns at startup).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Final

from loguru import logger

NS_PER_MS: Final[int] = 1_000_000
MAX_DRIFT_MS_DEFAULT: Final[int] = 500


@dataclass
class ClockState:
    last_check_ms: int = 0
    drift_ms: float = 0.0
    drift_alarm: bool = False
    consecutive_failures: int = 0


class UtcClock:
    """Monotonic UTC time + NTP drift watchdog."""

    def __init__(
        self,
        ntp_servers: tuple[str, ...] = ("time.google.com", "pool.ntp.org"),
        check_interval_s: int = 300,
        max_drift_ms: int = MAX_DRIFT_MS_DEFAULT,
    ) -> None:
        self._ntp_servers = ntp_servers
        self._check_interval_s = check_interval_s
        self._max_drift_ms = max_drift_ms
        self._state = ClockState()
        self._last_nonce_ms = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def now_ms() -> int:
        """Current UTC milliseconds. Backed by ``time.time_ns`` for precision."""
        return time.time_ns() // NS_PER_MS

    @staticmethod
    def now_ns() -> int:
        return time.time_ns()

    async def next_nonce_ms(self) -> int:
        """Strictly monotonic ms timestamp suitable for use as a Hyperliquid nonce."""
        async with self._lock:
            now = self.now_ms()
            if now <= self._last_nonce_ms:
                now = self._last_nonce_ms + 1
            self._last_nonce_ms = now
            return now

    @property
    def state(self) -> ClockState:
        return self._state

    @property
    def healthy(self) -> bool:
        return not self._state.drift_alarm

    async def _check_once(self) -> None:
        try:
            import ntplib  # type: ignore[import-untyped]
        except Exception:
            logger.warning("ntplib not installed; clock drift check disabled.")
            return

        loop = asyncio.get_running_loop()
        client = ntplib.NTPClient()
        for server in self._ntp_servers:
            try:
                resp = await loop.run_in_executor(None, lambda s=server: client.request(s, version=3, timeout=3))
                drift_ms = float(resp.offset) * 1000.0
                self._state.drift_ms = drift_ms
                self._state.last_check_ms = self.now_ms()
                self._state.consecutive_failures = 0
                if abs(drift_ms) > self._max_drift_ms:
                    self._state.drift_alarm = True
                    logger.error(f"Clock drift {drift_ms:+.1f}ms exceeds {self._max_drift_ms}ms; trading paused.")
                else:
                    if self._state.drift_alarm:
                        logger.success(f"Clock drift back within tolerance ({drift_ms:+.1f}ms); trading resumed.")
                    self._state.drift_alarm = False
                return
            except Exception as e:
                logger.debug(f"NTP {server} failed: {e}")
        self._state.consecutive_failures += 1
        if self._state.consecutive_failures >= 3:
            self._state.drift_alarm = True
            logger.error("All NTP probes failed; assuming drift alarm.")

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        logger.info("UtcClock watchdog started.")
        while not stop_event.is_set():
            await self._check_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._check_interval_s)
            except asyncio.TimeoutError:
                continue
        logger.info("UtcClock watchdog stopped.")


# Module-level singleton — every component should `from .clock import CLOCK`.
CLOCK = UtcClock()
