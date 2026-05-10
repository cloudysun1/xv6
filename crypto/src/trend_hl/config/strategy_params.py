"""Strategy hyperparameters — strongly typed and validated."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class KalmanParams(BaseModel):
    process_var_mu: float = Field(1e-7, gt=0, description="Q on level state")
    process_var_nu: float = Field(1e-9, gt=0, description="Q on velocity state")
    obs_var: float = Field(1e-4, gt=0, description="R measurement noise")
    init_var: float = Field(1.0, gt=0)


class MomentumParams(BaseModel):
    half_lives: list[int] = Field(default=[16, 64, 256], description="EWMA half-lives in bars")
    weights: list[float] = Field(default=[0.4, 0.4, 0.2])
    saturation_k: float = Field(1.0, gt=0)

    @field_validator("weights")
    @classmethod
    def _normalize(cls, v: list[float]) -> list[float]:
        s = sum(v)
        if s <= 0:
            raise ValueError("weights must sum > 0")
        return [w / s for w in v]


class VolatilityParams(BaseModel):
    yz_window: int = Field(48, ge=8)
    atr_window: int = Field(14, ge=4)
    blend_beta: float = Field(0.7, ge=0, le=1)
    annualization_bars_per_year: int = Field(525_600, gt=0)  # for 1m bars


class RegimeParams(BaseModel):
    adx_window: int = Field(14, ge=4)
    adx_trend_threshold: float = Field(20.0, ge=0)
    hurst_window: int = Field(128, ge=32)


class SignalParams(BaseModel):
    kalman: KalmanParams = KalmanParams()
    momentum: MomentumParams = MomentumParams()
    volatility: VolatilityParams = VolatilityParams()
    regime: RegimeParams = RegimeParams()
    min_signal_strength: float = Field(0.15, ge=0, le=1, description="Below this, force flat")
    snr_threshold: float = Field(1.5, ge=0, description="Kalman velocity / std")


class SizingParams(BaseModel):
    target_annual_vol: float = Field(0.30, gt=0, le=2.0, description="Per-strategy vol target")
    max_leverage_per_symbol: float = Field(2.0, gt=0)
    max_gross_leverage: float = Field(3.0, gt=0)
    kelly_fraction: float = Field(0.25, gt=0, le=1)
    min_notional_usd: float = Field(11.0, gt=0, description="Hyperliquid min order ~$10")


class ExitParams(BaseModel):
    chandelier_window: int = Field(22, ge=5)
    chandelier_atr_mult: float = Field(3.0, gt=0)
    time_stop_bars: int = Field(720, gt=0, description="Bars before time-stop kicks in")
    time_stop_min_pnl_sigma: float = Field(0.5, ge=0)
    sar_step: float = Field(0.02, gt=0)
    sar_max: float = Field(0.20, gt=0)


class RiskGateParams(BaseModel):
    daily_loss_limit_pct: float = Field(3.0, gt=0)
    per_symbol_dd_limit_pct: float = Field(5.0, gt=0)
    per_symbol_cooldown_min: int = Field(60 * 24, gt=0)
    blackswan_zscore: float = Field(8.0, gt=0)
    blackswan_cooldown_min: int = Field(30, gt=0)
    ws_heartbeat_timeout_s: int = Field(30, gt=0)
    clock_drift_max_ms: int = Field(500, gt=0)
    equity_floor_usd: float = Field(200.0, ge=0)


class ExecutionParams(BaseModel):
    bar_interval: str = Field("1m")
    rebalance_every_n_bars: int = Field(5, ge=1)
    maker_offset_ticks: int = Field(1, ge=0)
    maker_timeout_s: float = Field(2.0, gt=0, description="Wait for maker fill before IOC fallback")
    slice_max_pct_of_book: float = Field(0.15, gt=0, le=1)
    cancel_all_on_start: bool = True


class StrategyParams(BaseModel):
    name: str = "trend_hl_v1"
    signal: SignalParams = SignalParams()
    sizing: SizingParams = SizingParams()
    exit: ExitParams = ExitParams()
    risk: RiskGateParams = RiskGateParams()
    execution: ExecutionParams = ExecutionParams()
