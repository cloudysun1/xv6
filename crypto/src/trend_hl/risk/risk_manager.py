"""High-level Risk Manager — orchestrates sizing + exits + gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
from loguru import logger

from ..config.strategy_params import StrategyParams
from ..core.types import Position, Signal
from .exits import ExitState, chandelier_levels, parabolic_sar_step, should_exit, update_trailing
from .gates import GateContext, GateDecision, GateResult, RiskGates
from .sizing import position_size


@dataclass
class TargetPosition:
    symbol: str
    target_size: Decimal  # signed
    reason: str
    metadata: dict[str, float] = field(default_factory=dict)


class RiskManager:
    def __init__(self, params: StrategyParams) -> None:
        self._p = params
        self.gates = RiskGates(params.risk)
        self._exit_states: dict[str, ExitState] = {}
        self._rolling_sharpe: dict[str, float] = {}
        self._bars_per_year: int = params.signal.volatility.annualization_bars_per_year

    # ---------------- exit management ----------------
    def _exit_state(self, symbol: str) -> ExitState:
        if symbol not in self._exit_states:
            self._exit_states[symbol] = ExitState()
        return self._exit_states[symbol]

    def reset_exit(self, symbol: str, entry_price: float, is_long: bool) -> None:
        st = ExitState()
        st.entry_price = entry_price
        st.sar_long = is_long
        self._exit_states[symbol] = st

    def update_exits(
        self,
        symbol: str,
        is_long: bool,
        bars: dict[str, np.ndarray],
    ) -> None:
        st = self._exit_state(symbol)
        st.bars_in_position += 1
        long_stop, short_stop = chandelier_levels(
            bars["high"], bars["low"], bars["close"],
            window=self._p.exit.chandelier_window,
            atr_mult=self._p.exit.chandelier_atr_mult,
        )
        update_trailing(st, is_long, long_stop, short_stop)
        parabolic_sar_step(
            st, float(bars["high"][-1]), float(bars["low"][-1]),
            step=self._p.exit.sar_step, max_af=self._p.exit.sar_max,
        )

    def evaluate_exit(
        self,
        symbol: str,
        is_long: bool,
        last_close: float,
        sigma_bar: float,
    ) -> tuple[bool, str]:
        st = self._exit_state(symbol)
        return should_exit(
            st, is_long, last_close, sigma_bar,
            time_stop_bars=self._p.exit.time_stop_bars,
            time_stop_min_pnl_sigma=self._p.exit.time_stop_min_pnl_sigma,
        )

    # ---------------- target sizing ----------------
    def compute_target(
        self,
        signal: Signal,
        equity_usd: float,
        mid_price: float,
        weight: float,
        gate_ctx: GateContext,
        existing_position: Position | None,
    ) -> tuple[TargetPosition, GateResult]:
        sigma = signal.metadata.get("sigma_bar", 0.0)
        sharpe = self._rolling_sharpe.get(signal.symbol, 0.0)

        size, sz_meta = position_size(
            equity_usd=equity_usd,
            sigma_bar=sigma,
            signal_strength=signal.strength,
            mid_price=mid_price,
            weight=weight,
            rolling_sharpe=sharpe,
            params=self._p.sizing,
            bars_per_year=self._bars_per_year,
        )

        gate = self.gates.evaluate_pretrade(gate_ctx, signal.symbol, sz_meta["notional_usd"])

        if gate.decision != GateDecision.ALLOW:
            target_size = (existing_position.size if existing_position else Decimal(0)) \
                if gate.decision == GateDecision.BLOCK \
                else Decimal(0)  # KILL → flat
            return TargetPosition(
                symbol=signal.symbol, target_size=target_size,
                reason=f"gate:{gate.reason}", metadata=sz_meta,
            ), gate

        # Exit override: if we have an open position and exit fires → flat
        if existing_position is not None and not existing_position.is_flat:
            is_long = existing_position.size > 0
            sigma_bar = signal.metadata.get("sigma_bar", 0.0)
            close_px = mid_price
            self.update_exits(signal.symbol, is_long, _bars_from_signal(signal))  # no-op if no bars in meta
            exit_now, exit_reason = self.evaluate_exit(signal.symbol, is_long, close_px, sigma_bar)
            if exit_now:
                logger.info(f"[{signal.symbol}] exit triggered: {exit_reason}")
                return TargetPosition(
                    symbol=signal.symbol, target_size=Decimal(0),
                    reason=f"exit:{exit_reason}", metadata=sz_meta,
                ), gate

        return TargetPosition(
            symbol=signal.symbol, target_size=size,
            reason="signal_target", metadata=sz_meta,
        ), gate

    def update_rolling_sharpe(self, symbol: str, sharpe: float) -> None:
        self._rolling_sharpe[symbol] = sharpe


def _bars_from_signal(signal: Signal) -> dict[str, np.ndarray]:
    """Helper used when signal.metadata contains bar arrays (live path uses
    the registry instead). Returns empty arrays — caller must invoke
    update_exits with proper bars."""
    return {"high": np.empty(0), "low": np.empty(0), "close": np.empty(0)}
