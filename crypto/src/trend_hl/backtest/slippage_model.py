"""Linear book-walk slippage model."""

from __future__ import annotations

from decimal import Decimal


def book_walk_slippage(
    side: str,
    notional_usd: float,
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
) -> tuple[float, float]:
    """Walk the book to fill ``notional_usd``; return (avg_px, slippage_bps).

    bids/asks are lists of (price, size) sorted best-first.
    """
    levels = asks if side == "buy" else bids
    if not levels:
        return 0.0, float("inf")
    best = levels[0][0]
    remaining = notional_usd
    weighted_px = 0.0
    filled_notional = 0.0
    for px, sz in levels:
        cap = px * sz
        take = min(remaining, cap)
        weighted_px += px * take
        filled_notional += take
        remaining -= take
        if remaining <= 0:
            break
    if filled_notional == 0:
        return 0.0, float("inf")
    avg = weighted_px / filled_notional
    slip_bps = (avg / best - 1.0) * 1e4 * (1 if side == "buy" else -1)
    return avg, slip_bps


def maker_taker_fee(notional_usd: float, is_maker: bool) -> float:
    """Hyperliquid fee schedule (taker 3.5bps, maker -1bps rebate)."""
    rate = -0.0001 if is_maker else 0.00035
    return notional_usd * rate
