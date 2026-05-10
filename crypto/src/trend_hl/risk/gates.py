"""Hard risk gates (L1-L5). Fail-closed by design."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from loguru import logger

from ..config.strategy_params import RiskGateParams


class GateDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    KILL = "kill"  # close all + halt


@dataclass
class GateContext:
    equity_usd: float
    daily_pnl_pct: float
    ws_healthy: bool
    clock_drift_ms: float
    last_bar_z: float = 0.0  # latest 1-bar return z-score
    in_cooldown_until_ms: int = 0
    per_symbol_cooldowns: dict[str, int] = field(default_factory=dict)
    per_symbol_dd: dict[str, float] = field(default_factory=dict)
    open_notional_usd: float = 0.0


@dataclass
class GateResult:
    decision: GateDecision
    reason: str
    metadata: dict[str, float] = field(default_factory=dict)


class RiskGates:
    def __init__(self, params: RiskGateParams) -> None:
        self._p = params
        self._daily_anchor_pnl: float | None = None
        self._kill_engaged: bool = False
        self._kill_reason: str = ""

    @property
    def killed(self) -> bool:
        return self._kill_engaged

    def kill(self, reason: str) -> None:
        if not self._kill_engaged:
            logger.error(f"KILL-SWITCH ENGAGED: {reason}")
            self._kill_engaged = True
            self._kill_reason = reason

    def reset_kill(self, operator_token: str) -> None:
        # require explicit operator token to undo kill
        if operator_token == "RESET":
            logger.warning("Kill-switch manually reset by operator")
            self._kill_engaged = False
            self._kill_reason = ""

    def evaluate_pretrade(self, ctx: GateContext, symbol: str, intended_notional: float) -> GateResult:
        if self._kill_engaged:
            return GateResult(GateDecision.KILL, f"kill_engaged:{self._kill_reason}")

        # L4 — system health
        if not ctx.ws_healthy:
            return GateResult(GateDecision.BLOCK, "ws_unhealthy")
        if abs(ctx.clock_drift_ms) > self._p.clock_drift_max_ms:
            return GateResult(GateDecision.BLOCK, "clock_drift",
                              {"drift_ms": ctx.clock_drift_ms})

        # L1 — equity floor
        if ctx.equity_usd < self._p.equity_floor_usd:
            self.kill(f"equity_below_floor: {ctx.equity_usd:.2f} < {self._p.equity_floor_usd}")
            return GateResult(GateDecision.KILL, "equity_floor")

        # L3 — daily loss
        if ctx.daily_pnl_pct < -abs(self._p.daily_loss_limit_pct):
            self.kill(f"daily_loss: {ctx.daily_pnl_pct:.2f}%")
            return GateResult(GateDecision.KILL, "daily_loss_limit")

        # cool-downs
        now_ms = int(time.time() * 1000)
        if ctx.in_cooldown_until_ms > now_ms:
            return GateResult(GateDecision.BLOCK, "global_cooldown",
                              {"until_ms": ctx.in_cooldown_until_ms})
        sym_cd = ctx.per_symbol_cooldowns.get(symbol, 0)
        if sym_cd > now_ms:
            return GateResult(GateDecision.BLOCK, f"symbol_cooldown:{symbol}",
                              {"until_ms": sym_cd})

        # L5 — black swan
        if abs(ctx.last_bar_z) > self._p.blackswan_zscore:
            return GateResult(GateDecision.BLOCK, "blackswan",
                              {"bar_z": ctx.last_bar_z})

        # per-symbol drawdown
        dd = ctx.per_symbol_dd.get(symbol, 0.0)
        if dd < -abs(self._p.per_symbol_dd_limit_pct):
            return GateResult(GateDecision.BLOCK, f"symbol_dd:{symbol}",
                              {"dd_pct": dd})

        return GateResult(GateDecision.ALLOW, "ok")
