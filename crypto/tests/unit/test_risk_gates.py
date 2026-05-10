from __future__ import annotations

import time
from decimal import Decimal

from trend_hl.config.strategy_params import RiskGateParams
from trend_hl.risk.gates import GateContext, GateDecision, RiskGates


def _ctx(**kw) -> GateContext:
    base = dict(equity_usd=10_000, daily_pnl_pct=0.0, ws_healthy=True, clock_drift_ms=0.0)
    base.update(kw)
    return GateContext(**base)


def test_gate_blocks_on_ws_unhealthy() -> None:
    g = RiskGates(RiskGateParams())
    r = g.evaluate_pretrade(_ctx(ws_healthy=False), "BTC", 100)
    assert r.decision is GateDecision.BLOCK


def test_gate_kills_on_equity_floor() -> None:
    g = RiskGates(RiskGateParams(equity_floor_usd=500))
    r = g.evaluate_pretrade(_ctx(equity_usd=400), "BTC", 100)
    assert r.decision is GateDecision.KILL
    assert g.killed


def test_gate_kills_on_daily_loss() -> None:
    g = RiskGates(RiskGateParams(daily_loss_limit_pct=3.0))
    r = g.evaluate_pretrade(_ctx(daily_pnl_pct=-3.5), "BTC", 100)
    assert r.decision is GateDecision.KILL


def test_gate_blocks_on_drift() -> None:
    g = RiskGates(RiskGateParams(clock_drift_max_ms=200))
    r = g.evaluate_pretrade(_ctx(clock_drift_ms=500), "BTC", 100)
    assert r.decision is GateDecision.BLOCK
