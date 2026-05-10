"""Bar-by-bar event-driven backtest engine.

Re-uses the live ``TrendFollower`` to guarantee implementation parity. The
synthetic exchange applies maker fills at the bar OHLC midpoint and charges
taker fees + symmetric slippage.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
from loguru import logger

from ..config.settings import Universe
from ..config.strategy_params import StrategyParams
from ..core.types import AccountState, Bar, L2Book, L2Level, Position, SymbolMeta
from ..data.bar_aggregator import BarBufferRegistry
from ..exchange.paper_adapter import PaperAdapter
from ..execution.executor import Executor
from ..strategy.trend_follower import TrendFollower


@dataclass
class BacktestResult:
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    trades: int = 0
    fees: float = 0.0


class Backtester:
    def __init__(
        self,
        params: StrategyParams,
        universe: Universe,
        bar_data: dict[str, pl.DataFrame],
        starting_equity: Decimal = Decimal("10000"),
        interval: str = "1m",
    ) -> None:
        self._p = params
        self._u = universe
        self._bars = bar_data
        self._interval = interval
        self._equity0 = starting_equity
        self._strategy = TrendFollower(params, universe)
        self._registry = BarBufferRegistry(max_bars=5000)
        self._adapter = PaperAdapter(starting_equity=starting_equity)
        self._executor = Executor(self._adapter, params.execution)
        self._meta: dict[str, SymbolMeta] = {}

    def _build_synthetic_meta(self) -> None:
        for sym in self._bars:
            self._meta[sym] = SymbolMeta(
                symbol=sym, sz_decimals=4, px_decimals=2,
                max_leverage=20, min_size=Decimal("0.0001"),
            )
        self._adapter.set_meta(self._meta)

    def _book_from_bar(self, sym: str, bar: Bar) -> L2Book:
        spread = bar.close * 5e-5  # 0.5bp synthetic
        bid = bar.close - spread / 2
        ask = bar.close + spread / 2
        size = max(bar.volume * 0.1, 1.0)
        return L2Book(
            symbol=sym, ts_ms=bar.close_time_ms,
            bids=(L2Level(price=bid, size=size),),
            asks=(L2Level(price=ask, size=size),),
        )

    async def run(self) -> BacktestResult:
        self._build_synthetic_meta()
        result = BacktestResult()

        # align all symbol bars on common timeline
        all_ts = sorted(set(t for df in self._bars.values() for t in df["open_time_ms"].to_list()))
        per_sym_iter = {
            s: iter(df.sort("open_time_ms").iter_rows(named=True))
            for s, df in self._bars.items()
        }
        next_bar: dict[str, dict | None] = {s: next(it, None) for s, it in per_sym_iter.items()}

        for ts in all_ts:
            books: dict[str, L2Book] = {}
            for sym in list(next_bar.keys()):
                row = next_bar[sym]
                if row is None or row["open_time_ms"] != ts:
                    continue
                bar = Bar(
                    symbol=sym, interval=self._interval,
                    open_time_ms=int(row["open_time_ms"]),
                    close_time_ms=int(row["close_time_ms"]),
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=float(row.get("volume", 0)),
                    n_trades=int(row.get("n_trades", 0)),
                )
                buf = self._registry.get_or_create(sym, self._interval)
                await buf.upsert(bar)
                book = self._book_from_bar(sym, bar)
                self._adapter.update_book(book)
                books[sym] = book
                next_bar[sym] = next(per_sym_iter[sym], None)

            account = await self._adapter.fetch_account()

            decision = self._strategy.step(
                ts_ms=ts, registry=self._registry, interval=self._interval,
                account=account, books=books,
                ws_healthy=True, clock_drift_ms=0.0,
            )
            targets = {s: t.target_size for s, t in decision.targets.items()}
            await self._executor.execute_targets(targets, account, books, self._meta)

            account_after = await self._adapter.fetch_account()
            result.equity_curve.append((ts, float(account_after.equity)))

        result.trades = len(self._adapter._fills)  # type: ignore[attr-defined]
        result.fees = float(sum(f.fee for f in self._adapter._fills))  # type: ignore[attr-defined]
        return result
