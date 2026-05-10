"""Numerical helpers — small, vectorized, JIT-able."""

from __future__ import annotations

import math

import numpy as np


def safe_log_returns(closes: np.ndarray) -> np.ndarray:
    """Log returns with leading 0 padding."""
    if closes.size < 2:
        return np.zeros_like(closes)
    out = np.zeros_like(closes, dtype=np.float64)
    out[1:] = np.log(closes[1:]) - np.log(closes[:-1])
    return out


def ewm_mean(x: np.ndarray, alpha: float) -> np.ndarray:
    """Exponentially weighted mean, recursive form."""
    if x.size == 0:
        return x.copy()
    out = np.empty_like(x, dtype=np.float64)
    out[0] = x[0]
    one_minus = 1.0 - alpha
    for i in range(1, x.size):
        out[i] = alpha * x[i] + one_minus * out[i - 1]
    return out


def ewm_std(x: np.ndarray, alpha: float, eps: float = 1e-12) -> np.ndarray:
    """Exponentially weighted standard deviation."""
    if x.size == 0:
        return x.copy()
    mean = ewm_mean(x, alpha)
    var = np.empty_like(x, dtype=np.float64)
    var[0] = 0.0
    one_minus = 1.0 - alpha
    for i in range(1, x.size):
        diff = x[i] - mean[i]
        var[i] = alpha * diff * diff + one_minus * var[i - 1]
    return np.sqrt(var + eps)


def half_life_to_alpha(half_life_periods: float) -> float:
    """Convert EWMA half-life (in periods) to alpha."""
    return 1.0 - math.exp(-math.log(2.0) / max(half_life_periods, 1e-9))


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def signed_tanh_saturation(x: float, scale: float) -> float:
    """tanh(x/scale) — bounded soft signal."""
    if scale <= 0:
        return 0.0
    return math.tanh(x / scale)
