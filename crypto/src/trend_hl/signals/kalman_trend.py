"""Constant-velocity Kalman filter for log-price denoising.

State: x = [mu, nu]^T   (level, velocity)
Transition: F = [[1, dt], [0, 1]], Q diag(q_mu, q_nu)
Observation: H = [1, 0], R = obs_var

We expose a streaming :class:`KalmanTrendFilter` that ingests one log-price at
a time and yields ``(mu_hat, nu_hat, nu_std)`` for the signal layer. ``nu_std``
is the marginal stdev of the velocity from the posterior covariance — used as
the SNR denominator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class KalmanState:
    x: np.ndarray  # (2,)
    P: np.ndarray  # (2,2)
    initialized: bool = False


class KalmanTrendFilter:
    def __init__(
        self,
        process_var_mu: float = 1e-7,
        process_var_nu: float = 1e-9,
        obs_var: float = 1e-4,
        init_var: float = 1.0,
        dt: float = 1.0,
    ) -> None:
        self._Q = np.array([[process_var_mu, 0.0], [0.0, process_var_nu]], dtype=np.float64)
        self._R = float(obs_var)
        self._dt = float(dt)
        self._F = np.array([[1.0, self._dt], [0.0, 1.0]], dtype=np.float64)
        self._H = np.array([[1.0, 0.0]], dtype=np.float64)
        self._init_var = float(init_var)
        self._state = KalmanState(x=np.zeros(2), P=np.eye(2) * init_var)

    def reset(self) -> None:
        self._state = KalmanState(x=np.zeros(2), P=np.eye(2) * self._init_var)

    def update(self, log_price: float) -> tuple[float, float, float]:
        s = self._state
        if not s.initialized:
            s.x = np.array([log_price, 0.0])
            s.P = np.eye(2) * self._init_var
            s.initialized = True
            return float(s.x[0]), float(s.x[1]), float(math.sqrt(s.P[1, 1]))

        # predict
        x_pred = self._F @ s.x
        P_pred = self._F @ s.P @ self._F.T + self._Q

        # innovation
        y = log_price - float(self._H @ x_pred)
        S = float(self._H @ P_pred @ self._H.T) + self._R
        K = (P_pred @ self._H.T).flatten() / S  # (2,)

        # update
        s.x = x_pred + K * y
        I_KH = np.eye(2) - np.outer(K, self._H.flatten())
        s.P = I_KH @ P_pred

        return float(s.x[0]), float(s.x[1]), float(math.sqrt(max(s.P[1, 1], 0.0)))

    def warmup(self, log_prices: np.ndarray) -> tuple[float, float, float]:
        mu = nu = std = 0.0
        for lp in log_prices:
            mu, nu, std = self.update(float(lp))
        return mu, nu, std
