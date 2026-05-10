"""Exit logic: Chandelier (trailing), Parabolic SAR, time-stop."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .. import signals as sig


@dataclass
class ExitState:
    chandelier_long: float = -math.inf
    chandelier_short: float = math.inf
    sar: float | None = None
    sar_af: float = 0.02
    sar_ep: float = 0.0  # extreme point
    sar_long: bool = True
    bars_in_position: int = 0
    entry_price: float = 0.0


def chandelier_levels(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int = 22,
    atr_mult: float = 3.0,
) -> tuple[float, float]:
    if closes.size < window + 1:
        return -math.inf, math.inf
    atr_arr = sig.atr(highs, lows, closes, window=window)
    last_atr = float(atr_arr[-1])
    if math.isnan(last_atr):
        return -math.inf, math.inf
    hh = float(highs[-window:].max())
    ll = float(lows[-window:].min())
    long_stop = hh - atr_mult * last_atr
    short_stop = ll + atr_mult * last_atr
    return long_stop, short_stop


def update_trailing(
    state: ExitState,
    is_long: bool,
    long_stop: float,
    short_stop: float,
) -> None:
    """Trail only in the favourable direction."""
    if is_long:
        state.chandelier_long = max(state.chandelier_long, long_stop)
    else:
        state.chandelier_short = min(state.chandelier_short, short_stop)


def parabolic_sar_step(
    state: ExitState,
    high: float,
    low: float,
    step: float = 0.02,
    max_af: float = 0.20,
) -> float:
    """Update SAR in-place; return current SAR level."""
    if state.sar is None:
        state.sar = low if state.sar_long else high
        state.sar_ep = high if state.sar_long else low
        state.sar_af = step
        return state.sar

    sar_prev = state.sar
    af = state.sar_af
    ep = state.sar_ep
    sar = sar_prev + af * (ep - sar_prev)

    if state.sar_long:
        sar = min(sar, low)
        if high > ep:
            ep = high
            af = min(af + step, max_af)
        if low < sar:
            # flip
            state.sar_long = False
            sar = ep
            ep = low
            af = step
    else:
        sar = max(sar, high)
        if low < ep:
            ep = low
            af = min(af + step, max_af)
        if high > sar:
            state.sar_long = True
            sar = ep
            ep = high
            af = step

    state.sar = sar
    state.sar_ep = ep
    state.sar_af = af
    return sar


def should_exit(
    state: ExitState,
    is_long: bool,
    last_close: float,
    sigma_bar: float,
    time_stop_bars: int,
    time_stop_min_pnl_sigma: float,
) -> tuple[bool, str]:
    """Return (exit?, reason)."""
    if is_long and last_close <= state.chandelier_long:
        return True, "chandelier_long"
    if (not is_long) and last_close >= state.chandelier_short:
        return True, "chandelier_short"
    if state.sar is not None:
        if is_long and last_close <= state.sar:
            return True, "sar_long"
        if (not is_long) and last_close >= state.sar:
            return True, "sar_short"
    if state.bars_in_position >= time_stop_bars and state.entry_price > 0:
        pnl = (last_close - state.entry_price) / state.entry_price
        if not is_long:
            pnl = -pnl
        if sigma_bar > 0 and pnl < time_stop_min_pnl_sigma * sigma_bar:
            return True, "time_stop"
    return False, ""
