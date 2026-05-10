from __future__ import annotations

from trend_hl.config.strategy_params import SizingParams
from trend_hl.risk.sizing import position_size, vol_target_notional


def test_vol_target_zero_when_sigma_zero() -> None:
    n = vol_target_notional(10000, 0.0, 525_600, 0.3, 1.0)
    assert n == 0.0


def test_position_size_respects_min_notional() -> None:
    p = SizingParams(min_notional_usd=20)
    size, meta = position_size(
        equity_usd=100, sigma_bar=1e-3, signal_strength=0.05,
        mid_price=100.0, weight=1.0, rolling_sharpe=0.0,
        params=p, bars_per_year=525_600,
    )
    assert size == 0


def test_position_size_caps_leverage() -> None:
    p = SizingParams(target_annual_vol=10.0, max_leverage_per_symbol=2.0,
                     min_notional_usd=1.0)
    _, meta = position_size(
        equity_usd=10_000, sigma_bar=1e-5, signal_strength=1.0,
        mid_price=100.0, weight=1.0, rolling_sharpe=0.0,
        params=p, bars_per_year=525_600,
    )
    assert abs(meta["notional_usd"]) <= p.max_leverage_per_symbol * 10_000 + 1e-6
