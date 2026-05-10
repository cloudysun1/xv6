"""Market-regime detection: ADX (Wilder) + rough Hurst exponent."""

from __future__ import annotations

import numpy as np

from ..core.enums import Regime


def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, window: int = 14) -> float:
    n = closes.size
    if n < window * 2 + 1:
        return float("nan")
    up = highs[1:] - highs[:-1]
    down = lows[:-1] - lows[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    prev_close = closes[:-1]
    tr = np.maximum(highs[1:] - lows[1:], np.maximum(np.abs(highs[1:] - prev_close), np.abs(lows[1:] - prev_close)))
    # Wilder smoothing
    def wilder(arr: np.ndarray) -> np.ndarray:
        out = np.empty_like(arr)
        out[: window - 1] = np.nan
        out[window - 1] = arr[:window].sum()
        for i in range(window, arr.size):
            out[i] = out[i - 1] - out[i - 1] / window + arr[i]
        return out
    tr_s = wilder(tr)
    pdm_s = wilder(plus_dm)
    mdm_s = wilder(minus_dm)
    with np.errstate(invalid="ignore", divide="ignore"):
        plus_di = 100.0 * pdm_s / tr_s
        minus_di = 100.0 * mdm_s / tr_s
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    # ADX = Wilder average of DX over window
    valid = dx[~np.isnan(dx)]
    if valid.size < window:
        return float("nan")
    adx_arr = np.empty_like(valid)
    adx_arr[: window - 1] = np.nan
    adx_arr[window - 1] = valid[:window].mean()
    for i in range(window, valid.size):
        adx_arr[i] = (adx_arr[i - 1] * (window - 1) + valid[i]) / window
    return float(adx_arr[-1])


def hurst_rs(series: np.ndarray, max_lag: int = 64) -> float:
    """Rescaled-range Hurst estimator. H>0.5 trending, H<0.5 mean-reverting."""
    n = series.size
    if n < max_lag * 2:
        return float("nan")
    lags = np.unique(np.logspace(0.5, np.log10(max_lag), 10).astype(int))
    tau = []
    for lag in lags:
        if lag < 2:
            continue
        diff = series[lag:] - series[:-lag]
        std = diff.std()
        if std <= 0:
            continue
        tau.append((lag, std))
    if len(tau) < 4:
        return float("nan")
    lags_arr = np.log([t[0] for t in tau])
    stds_arr = np.log([t[1] for t in tau])
    slope, _ = np.polyfit(lags_arr, stds_arr, 1)
    return float(slope)


def classify_regime(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    adx_window: int = 14,
    adx_threshold: float = 20.0,
    hurst_window: int = 128,
) -> tuple[Regime, dict[str, float]]:
    adx_v = adx(highs, lows, closes, adx_window)
    h = hurst_rs(closes[-hurst_window:], max_lag=min(64, hurst_window // 2)) if closes.size >= hurst_window else float("nan")
    meta = {"adx": adx_v if adx_v == adx_v else 0.0, "hurst": h if h == h else 0.5}

    direction_up = closes[-1] > closes[-min(adx_window, closes.size)]

    if adx_v != adx_v:  # NaN
        return Regime.CHOP, meta
    if adx_v >= adx_threshold:
        return (Regime.TRENDING_UP if direction_up else Regime.TRENDING_DOWN), meta
    if h < 0.45:
        return Regime.RANGING, meta
    return Regime.CHOP, meta
