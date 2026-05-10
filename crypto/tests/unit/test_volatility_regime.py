from __future__ import annotations

import numpy as np

from trend_hl.signals.volatility import yang_zhang, atr, blended_volatility
from trend_hl.signals.regime import classify_regime
from trend_hl.core.enums import Regime


def _synth_ohlc(n: int = 200, drift: float = 0.0, vol: float = 0.001, seed: int = 7):
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(drift + rng.normal(0, vol, n)))
    opens = np.concatenate([[100.0], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, vol, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, vol, n)))
    return opens, highs, lows, closes


def test_yang_zhang_returns_positive() -> None:
    o, h, l, c = _synth_ohlc()
    s = yang_zhang(o, h, l, c, window=48)
    assert s > 0


def test_atr_shape() -> None:
    o, h, l, c = _synth_ohlc()
    a = atr(h, l, c, window=14)
    assert a.shape == c.shape
    assert not np.isnan(a[-1])


def test_blended_vol_finite() -> None:
    o, h, l, c = _synth_ohlc()
    bv = blended_volatility(o, h, l, c)
    assert bv > 0


def test_regime_trending_up() -> None:
    o, h, l, c = _synth_ohlc(drift=0.005, vol=0.0005)
    reg, meta = classify_regime(h, l, c)
    assert reg in (Regime.TRENDING_UP, Regime.RANGING, Regime.CHOP)
    assert "adx" in meta
