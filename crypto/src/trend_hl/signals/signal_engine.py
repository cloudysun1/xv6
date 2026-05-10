"""Composite signal engine combining Kalman + momentum + regime."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config.strategy_params import SignalParams
from ..core.enums import Regime, SignalDirection
from ..core.types import Signal
from ..utils.math_ops import safe_log_returns
from .kalman_trend import KalmanTrendFilter
from .momentum_bands import momentum_signal
from .regime import classify_regime
from .volatility import blended_volatility


@dataclass
class SignalContext:
    """Per-symbol persistent state for the engine."""

    symbol: str
    kalman: KalmanTrendFilter
    last_signal: float = 0.0
    bars_seen: int = 0


class SignalEngine:
    """Stateless w.r.t. params, stateful w.r.t. per-symbol Kalman filters."""

    def __init__(self, params: SignalParams) -> None:
        self._p = params
        self._ctx: dict[str, SignalContext] = {}

    def _ctx_for(self, symbol: str) -> SignalContext:
        if symbol not in self._ctx:
            kp = self._p.kalman
            self._ctx[symbol] = SignalContext(
                symbol=symbol,
                kalman=KalmanTrendFilter(
                    process_var_mu=kp.process_var_mu,
                    process_var_nu=kp.process_var_nu,
                    obs_var=kp.obs_var,
                    init_var=kp.init_var,
                ),
            )
        return self._ctx[symbol]

    def warmup(self, symbol: str, closes: np.ndarray) -> None:
        if closes.size < 2:
            return
        ctx = self._ctx_for(symbol)
        ctx.kalman.reset()
        ctx.kalman.warmup(np.log(closes))
        ctx.bars_seen = closes.size

    def compute(
        self,
        symbol: str,
        bars: dict[str, np.ndarray],
        ts_ms: int,
    ) -> Signal:
        opens = bars["open"]
        highs = bars["high"]
        lows = bars["low"]
        closes = bars["close"]

        ctx = self._ctx_for(symbol)
        if closes.size < 64:
            return Signal(symbol=symbol, ts_ms=ts_ms,
                          direction=SignalDirection.FLAT, strength=0.0,
                          target_leverage=0.0, metadata={"reason": "insufficient_data"})

        # 1. Kalman state on latest log price
        if ctx.bars_seen < closes.size:
            # incremental update for new bars
            for i in range(max(ctx.bars_seen, 1), closes.size):
                ctx.kalman.update(float(np.log(closes[i])))
            ctx.bars_seen = closes.size
        mu_hat, nu_hat, nu_std = ctx.kalman.update(float(np.log(closes[-1])))
        snr = (nu_hat / nu_std) if nu_std > 0 else 0.0
        kalman_sig = math.tanh(snr / max(self._p.snr_threshold, 1e-9))

        # 2. Momentum
        rets = safe_log_returns(closes)
        mom_sig, mom_meta = momentum_signal(
            rets,
            self._p.momentum.half_lives,
            self._p.momentum.weights,
            self._p.momentum.saturation_k,
        )

        # 3. Volatility
        sigma = blended_volatility(
            opens, highs, lows, closes,
            yz_window=self._p.volatility.yz_window,
            atr_window=self._p.volatility.atr_window,
            beta=self._p.volatility.blend_beta,
        )

        # 4. Regime
        regime, regime_meta = classify_regime(
            highs, lows, closes,
            adx_window=self._p.regime.adx_window,
            adx_threshold=self._p.regime.adx_trend_threshold,
            hurst_window=self._p.regime.hurst_window,
        )

        # 5. Combine — multiplicative gating
        raw = 0.5 * kalman_sig + 0.5 * mom_sig
        # require Kalman+momentum agreement to take a position
        agree = 1.0 if (kalman_sig * mom_sig) >= 0 else 0.3
        regime_gate = 1.0 if regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN) else 0.4
        snr_gate = 1.0 if abs(snr) >= self._p.snr_threshold else 0.5
        strength = float(np.clip(raw * agree * regime_gate * snr_gate, -1.0, 1.0))

        if abs(strength) < self._p.min_signal_strength:
            direction = SignalDirection.FLAT
            target_lev = 0.0
        else:
            direction = SignalDirection.LONG if strength > 0 else SignalDirection.SHORT
            target_lev = strength  # downstream sizing translates to actual leverage

        ctx.last_signal = strength
        meta = {
            "kalman_mu": mu_hat,
            "kalman_nu": nu_hat,
            "kalman_nu_std": nu_std,
            "kalman_snr": snr,
            "kalman_sig": kalman_sig,
            "mom_sig": mom_sig,
            "agree": agree,
            "regime": regime.value,  # type: ignore[dict-item]
            "regime_gate": regime_gate,
            "snr_gate": snr_gate,
            "sigma_bar": float(sigma) if sigma == sigma else 0.0,
            "strength": strength,
            **mom_meta,
            **regime_meta,
        }
        return Signal(
            symbol=symbol, ts_ms=ts_ms, direction=direction,
            strength=strength, target_leverage=target_lev, metadata=meta,  # type: ignore[arg-type]
        )
