"""Volatility estimators: Yang-Zhang, ATR, blended."""

from __future__ import annotations

import math

import numpy as np


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, window: int = 14) -> np.ndarray:
    if highs.size == 0:
        return np.empty(0)
    prev_close = np.concatenate([[closes[0]], closes[:-1]])
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
    out = np.empty_like(tr)
    if tr.size < window:
        out[:] = np.nan
        return out
    # Wilder's smoothing
    out[: window - 1] = np.nan
    out[window - 1] = tr[:window].mean()
    for i in range(window, tr.size):
        out[i] = (out[i - 1] * (window - 1) + tr[i]) / window
    return out


def yang_zhang(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 48,
) -> float:
    """Yang-Zhang volatility estimator (per-bar). Returns *per-bar* sigma."""
    n = closes.size
    if n < window + 1:
        return float("nan")
    o = np.log(opens[-window:])
    h = np.log(highs[-window:])
    l_ = np.log(lows[-window:])
    c = np.log(closes[-window:])
    c_prev = np.log(closes[-window - 1:-1])

    # overnight return
    r_o = o - c_prev
    r_c = c - o
    sigma_o2 = float(np.var(r_o, ddof=1))
    sigma_c2 = float(np.var(r_c, ddof=1))
    rs = (h - c) * (h - o) + (l_ - c) * (l_ - o)
    sigma_rs2 = float(np.mean(rs))

    k = 0.34 / (1.34 + (window + 1) / max(window - 1, 1))
    var = sigma_o2 + k * sigma_c2 + (1.0 - k) * sigma_rs2
    return math.sqrt(max(var, 0.0))


def blended_volatility(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    yz_window: int = 48,
    atr_window: int = 14,
    beta: float = 0.7,
) -> float:
    """Return blended *relative* volatility (sigma / price), per bar."""
    if closes.size < max(yz_window + 1, atr_window + 1):
        return float("nan")
    yz = yang_zhang(opens, highs, lows, closes, yz_window)
    atr_arr = atr(highs, lows, closes, atr_window)
    last_close = float(closes[-1])
    last_atr = float(atr_arr[-1]) if not math.isnan(atr_arr[-1]) else 0.0
    atr_rel = last_atr / max(last_close, 1e-12)
    if math.isnan(yz):
        yz = atr_rel
    return float(beta * yz + (1.0 - beta) * atr_rel)
