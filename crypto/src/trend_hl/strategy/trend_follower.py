"""TrendFollower strategy — orchestrates SignalEngine and RiskManager."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from loguru import logger

from ..config.settings import Universe
from ..config.strategy_params import StrategyParams
from ..core.types import AccountState, L2Book, Signal
from ..data.bar_aggregator import BarBufferRegistry
from ..risk.gates import GateContext
from ..risk.risk_manager import RiskManager, TargetPosition
from ..signals.signal_engine import SignalEngine


@dataclass
class StrategyDecision:
    signals: dict[str, Signal]
    targets: dict[str, TargetPosition]
    gate_ctx: GateContext


class TrendFollower:
    def __init__(self, params: StrategyParams, universe: Universe) -> None:
        self._p = params
        self._universe = universe
        self._weights: dict[str, float] = {u.symbol: u.weight for u in universe.active}
        self.signal_engine = SignalEngine(params.signal)
        self.risk_manager = RiskManager(params)

        self._equity_history: deque[Decimal] = deque(maxlen=2880)  # ~2d of 1m bars
        self._daily_anchor_equity: Decimal | None = None
        self._daily_anchor_day: int | None = None
        self._return_history: dict[str, deque[float]] = {
            u.symbol: deque(maxlen=2000) for u in universe.active
        }

    @property
    def universe(self) -> Universe:
        return self._universe

    def warmup(self, registry: BarBufferRegistry, interval: str) -> None:
        for u in self._universe.active:
            buf = registry.get(u.symbol, interval)
            if buf is None or len(buf) < 64:
                continue
            arrs = buf.to_numpy()
            self.signal_engine.warmup(u.symbol, arrs["close"])
            logger.info(f"[{u.symbol}] strategy warmup with {len(arrs['close'])} bars")

    def update_daily_anchor(self, ts_ms: int, equity: Decimal) -> None:
        day = ts_ms // (86400 * 1000)
        if self._daily_anchor_day != day:
            self._daily_anchor_equity = equity
            self._daily_anchor_day = day

    def daily_pnl_pct(self, equity: Decimal) -> float:
        if self._daily_anchor_equity is None or self._daily_anchor_equity == 0:
            return 0.0
        return float((equity - self._daily_anchor_equity) / self._daily_anchor_equity * 100)

    def step(
        self,
        ts_ms: int,
        registry: BarBufferRegistry,
        interval: str,
        account: AccountState,
        books: dict[str, L2Book],
        ws_healthy: bool,
        clock_drift_ms: float,
    ) -> StrategyDecision:
        self.update_daily_anchor(ts_ms, account.equity)
        self._equity_history.append(account.equity)
        gate_ctx = GateContext(
            equity_usd=float(account.equity),
            daily_pnl_pct=self.daily_pnl_pct(account.equity),
            ws_healthy=ws_healthy,
            clock_drift_ms=clock_drift_ms,
        )

        signals: dict[str, Signal] = {}
        targets: dict[str, TargetPosition] = {}

        for u in self._universe.active:
            buf = registry.get(u.symbol, interval)
            if buf is None or len(buf) < 64:
                continue
            bars = buf.to_numpy()
            sig = self.signal_engine.compute(u.symbol, bars, ts_ms)
            signals[u.symbol] = sig

            # rolling 1-bar return z for blackswan gate
            closes = bars["close"]
            if closes.size >= 2:
                r = float(closes[-1] / closes[-2] - 1.0)
                self._return_history[u.symbol].append(r)
                hist = list(self._return_history[u.symbol])
                if len(hist) >= 100:
                    import numpy as np
                    arr = np.asarray(hist[-500:])
                    sigma = float(arr.std())
                    if sigma > 0:
                        gate_ctx.last_bar_z = max(gate_ctx.last_bar_z, abs(r / sigma))

            book = books.get(u.symbol)
            if book is None:
                continue
            mid = book.mid

            existing = account.positions.get(u.symbol)
            target, gate = self.risk_manager.compute_target(
                signal=sig,
                equity_usd=float(account.equity),
                mid_price=mid,
                weight=self._weights[u.symbol],
                gate_ctx=gate_ctx,
                existing_position=existing,
            )
            # update exits with REAL bars when we are in a position
            if existing is not None and not existing.is_flat:
                is_long = existing.size > 0
                self.risk_manager.update_exits(u.symbol, is_long, bars)
            elif target.target_size != 0:
                # opening fresh
                self.risk_manager.reset_exit(
                    u.symbol, mid, is_long=(target.target_size > 0),
                )

            targets[u.symbol] = target

        return StrategyDecision(signals=signals, targets=targets, gate_ctx=gate_ctx)
