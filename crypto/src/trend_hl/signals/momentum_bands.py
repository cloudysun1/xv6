"""Multi-horizon EWMA momentum with tanh saturation."""

from __future__ import annotations

import numpy as np

from ..utils.math_ops import ewm_mean, ewm_std, half_life_to_alpha, signed_tanh_saturation


def momentum_signal(
    log_returns: np.ndarray,
    half_lives: list[int],
    weights: list[float],
    saturation_k: float = 1.0,
) -> tuple[float, dict[str, float]]:
    """Return aggregated signal in [-1,1] and per-band metadata."""
    if log_returns.size < 4:
        return 0.0, {}
    if len(half_lives) != len(weights):
        raise ValueError("half_lives and weights length mismatch")

    components: list[float] = []
    meta: dict[str, float] = {}
    for hl, w in zip(half_lives, weights):
        alpha = half_life_to_alpha(hl)
        m = ewm_mean(log_returns, alpha)
        s = ewm_std(log_returns, alpha)
        m_last = float(m[-1])
        s_last = float(s[-1])
        if s_last <= 0.0:
            comp = 0.0
        else:
            # band signal: sign by mean, magnitude saturated by std-units
            comp = signed_tanh_saturation(m_last, saturation_k * s_last)
        components.append(w * comp)
        meta[f"mom_hl_{hl}"] = float(comp)
        meta[f"mom_mean_{hl}"] = m_last
        meta[f"mom_std_{hl}"] = s_last

    agg = float(np.clip(sum(components), -1.0, 1.0))
    meta["mom_agg"] = agg
    return agg, meta
