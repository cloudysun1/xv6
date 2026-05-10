"""Position-sizing: vol-target × fractional Kelly × per-symbol cap."""

from __future__ import annotations

import math
from decimal import Decimal

from ..config.strategy_params import SizingParams


def vol_target_notional(
    equity_usd: float,
    sigma_bar: float,
    bars_per_year: int,
    target_annual_vol: float,
    signal_strength: float,
    weight: float = 1.0,
) -> float:
    """Return *signed* notional in USD.

    sigma_bar: per-bar relative volatility (e.g., 0.001 = 10 bps).
    """
    if sigma_bar <= 0 or equity_usd <= 0:
        return 0.0
    annual_vol = sigma_bar * math.sqrt(bars_per_year)
    if annual_vol <= 0:
        return 0.0
    raw_lev = (target_annual_vol / annual_vol) * signal_strength * weight
    return float(equity_usd * raw_lev)


def fractional_kelly_scale(
    rolling_sharpe: float,
    sigma_bar: float,
    fraction: float,
    bars_per_year: int,
) -> float:
    """Kelly scaler in [0, 1] applied on top of vol-target notional.

    Uses Sharpe×sigma to back out drift; shrinks toward 0 when uncertain.
    """
    if sigma_bar <= 0:
        return 0.0
    annual_vol = sigma_bar * math.sqrt(bars_per_year)
    mu = rolling_sharpe * annual_vol  # implied annual drift
    f_full = mu / max(annual_vol * annual_vol, 1e-12)
    f = fraction * f_full
    return max(0.0, min(1.0, f))


def cap_leverage(
    target_notional: float,
    equity_usd: float,
    max_leverage_per_symbol: float,
) -> float:
    if equity_usd <= 0:
        return 0.0
    cap = max_leverage_per_symbol * equity_usd
    return float(max(-cap, min(cap, target_notional)))


def size_to_decimal(notional_usd: float, mid_price: float) -> Decimal:
    """Convert signed notional → signed coin size. Caller will round to lot."""
    if mid_price <= 0:
        return Decimal(0)
    return Decimal(str(notional_usd / mid_price))


def position_size(
    equity_usd: float,
    sigma_bar: float,
    signal_strength: float,
    mid_price: float,
    weight: float,
    rolling_sharpe: float,
    params: SizingParams,
    bars_per_year: int,
) -> tuple[Decimal, dict[str, float]]:
    """End-to-end sizing returning *signed* coin size + diagnostics."""
    notional = vol_target_notional(
        equity_usd, sigma_bar, bars_per_year,
        params.target_annual_vol, signal_strength, weight,
    )
    kelly = fractional_kelly_scale(rolling_sharpe, sigma_bar, params.kelly_fraction, bars_per_year)
    notional *= kelly if kelly > 0 else 1.0  # if kelly==0 use vol-target only
    notional = cap_leverage(notional, equity_usd, params.max_leverage_per_symbol)

    if abs(notional) < params.min_notional_usd:
        notional = 0.0

    size = size_to_decimal(notional, mid_price)
    return size, {
        "notional_usd": notional,
        "kelly_scale": kelly,
        "annual_vol_est": sigma_bar * math.sqrt(bars_per_year) if sigma_bar > 0 else 0.0,
    }
