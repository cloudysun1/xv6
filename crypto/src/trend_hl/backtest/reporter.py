"""Plain-text backtest reporter (matplotlib/quantstats optional)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PerfStats:
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    n_trades: int
    avg_trade_fee: float


def compute_stats(equity_curve: list[tuple[int, float]], n_trades: int, fees: float,
                  bars_per_year: int = 525_600) -> PerfStats:
    if len(equity_curve) < 2:
        return PerfStats(0, 0, 0, 0, 0, n_trades, 0)
    eq0 = equity_curve[0][1]
    eqN = equity_curve[-1][1]
    total_ret = (eqN / eq0 - 1.0) * 100
    n_bars = len(equity_curve)
    cagr = ((eqN / eq0) ** (bars_per_year / max(n_bars, 1)) - 1.0) * 100
    rets = []
    peak = eq0
    max_dd = 0.0
    for _, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (eq / peak - 1.0) * 100
        if dd < max_dd:
            max_dd = dd
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1][1]
        cur = equity_curve[i][1]
        if prev > 0:
            rets.append(cur / prev - 1.0)
    if not rets:
        return PerfStats(total_ret, cagr, 0, 0, max_dd, n_trades, fees / max(n_trades, 1))
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / max(len(rets) - 1, 1)
    sigma = math.sqrt(var)
    sharpe = (mu / sigma * math.sqrt(bars_per_year)) if sigma > 0 else 0.0
    downs = [r for r in rets if r < 0]
    if downs:
        ddev = math.sqrt(sum(r * r for r in downs) / len(downs))
        sortino = (mu / ddev * math.sqrt(bars_per_year)) if ddev > 0 else 0.0
    else:
        sortino = 0.0
    return PerfStats(total_ret, cagr, sharpe, sortino, max_dd, n_trades, fees / max(n_trades, 1))


def report_text(stats: PerfStats) -> str:
    return (
        f"Total Return: {stats.total_return_pct:.2f}%\n"
        f"CAGR:         {stats.cagr_pct:.2f}%\n"
        f"Sharpe:       {stats.sharpe:.2f}\n"
        f"Sortino:      {stats.sortino:.2f}\n"
        f"Max DD:       {stats.max_drawdown_pct:.2f}%\n"
        f"# Trades:     {stats.n_trades}\n"
        f"Avg Fee/Tr:   {stats.avg_trade_fee:.4f}\n"
    )
