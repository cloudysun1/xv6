from __future__ import annotations

import numpy as np

from trend_hl.signals.kalman_trend import KalmanTrendFilter


def test_kalman_tracks_trend() -> None:
    rng = np.random.default_rng(42)
    n = 500
    drift = 0.0005
    log_p = np.cumsum(drift + rng.normal(0, 0.001, n))
    kf = KalmanTrendFilter(process_var_mu=1e-7, process_var_nu=1e-9, obs_var=1e-4)
    nu = 0.0
    for lp in log_p:
        _, nu, _ = kf.update(float(lp))
    assert nu > 0  # detect upward trend


def test_kalman_handles_constant_series() -> None:
    kf = KalmanTrendFilter()
    last_nu = 0.0
    for _ in range(200):
        _, last_nu, _ = kf.update(4.0)
    assert abs(last_nu) < 1e-3
