"""Equal-Risk-Contribution portfolio weights (cyclical-coordinate-descent)."""

from __future__ import annotations

import numpy as np


def erc_weights(cov: np.ndarray, max_iter: int = 200, tol: float = 1e-8) -> np.ndarray:
    """Solve for ERC weights w with w_i * (Sigma w)_i = const.

    Returns long-only weights summing to 1. Inputs must be a PSD covariance.
    """
    n = cov.shape[0]
    if n == 1:
        return np.array([1.0])
    w = np.full(n, 1.0 / n)
    for _ in range(max_iter):
        w_old = w.copy()
        sigma_w = cov @ w
        rc = w * sigma_w
        target = rc.mean()
        # gradient step
        for i in range(n):
            denom = sigma_w[i]
            if denom <= 0:
                continue
            w[i] = max(target / denom, 1e-9)
        w = w / w.sum()
        if np.linalg.norm(w - w_old, ord=1) < tol:
            break
    return w


def ledoit_wolf_shrink(returns: np.ndarray, shrink: float = 0.2) -> np.ndarray:
    """Quick Ledoit-Wolf-style shrinkage toward the diagonal."""
    if returns.ndim != 2:
        raise ValueError("returns must be 2D (T,N)")
    sample = np.cov(returns, rowvar=False)
    diag = np.diag(np.diag(sample))
    return (1.0 - shrink) * sample + shrink * diag
