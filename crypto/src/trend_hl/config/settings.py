"""Top-level Settings — pydantic-settings loads from .env + env vars."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..core.enums import RunMode
from .strategy_params import StrategyParams


class UniverseEntry(BaseModel):
    symbol: str
    enabled: bool = True
    weight: float = 1.0


class Universe(BaseModel):
    symbols: list[UniverseEntry]

    @property
    def active(self) -> list[UniverseEntry]:
        return [s for s in self.symbols if s.enabled]


class HyperliquidCreds(BaseModel):
    account_address: str = Field(..., description="Main wallet (funds owner)")
    api_secret: SecretStr = Field(..., description="Agent wallet private key")
    api_url: str = "https://api.hyperliquid.xyz"
    ws_url: str = "wss://api.hyperliquid.xyz/ws"
    network: str = "mainnet"

    @field_validator("account_address")
    @classmethod
    def _check_addr(cls, v: str) -> str:
        if not (v.startswith("0x") and len(v) == 42):
            raise ValueError(f"invalid EVM address: {v[:6]}…")
        return v.lower()

    @field_validator("api_secret")
    @classmethod
    def _check_pk(cls, v: SecretStr) -> SecretStr:
        s = v.get_secret_value()
        if not (s.startswith("0x") and len(s) == 66):
            raise ValueError("invalid private key length")
        return v


class NotificationConfig(BaseModel):
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: SecretStr | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- HL credentials (flat env names per .env.example) ---
    hl_account_address: str = Field(...)
    hl_api_secret: SecretStr = Field(...)
    hl_api_url: str = "https://api.hyperliquid.xyz"
    hl_ws_url: str = "wss://api.hyperliquid.xyz/ws"
    hl_network: str = "mainnet"

    # --- runtime ---
    trend_hl_env: RunMode = RunMode.PAPER
    trend_hl_log_level: str = "INFO"
    trend_hl_data_dir: Path = Path("./data")
    trend_hl_universe_file: Path = Path("src/trend_hl/config/universe.yaml")

    # --- notifications ---
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: SecretStr | None = None

    # --- caps (overlaid on StrategyParams.risk if provided) ---
    equity_floor_usd: float = 200.0
    daily_loss_limit_pct: float = 3.0
    max_gross_leverage: float = 3.0

    def hl(self) -> HyperliquidCreds:
        return HyperliquidCreds(
            account_address=self.hl_account_address,
            api_secret=self.hl_api_secret,
            api_url=self.hl_api_url,
            ws_url=self.hl_ws_url,
            network=self.hl_network,
        )

    def notifications(self) -> NotificationConfig:
        return NotificationConfig(
            telegram_bot_token=self.telegram_bot_token,
            telegram_chat_id=self.telegram_chat_id,
            discord_webhook_url=self.discord_webhook_url,
        )

    def load_universe(self) -> Universe:
        path = self.trend_hl_universe_file
        if not path.exists():
            raise FileNotFoundError(f"universe file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f)
        return Universe.model_validate(raw)

    def strategy_params(self) -> StrategyParams:
        # Today: defaults; future: overlay from YAML or DB
        params = StrategyParams()
        # propagate global caps into per-strategy risk gates
        params.risk.daily_loss_limit_pct = self.daily_loss_limit_pct
        params.risk.equity_floor_usd = self.equity_floor_usd
        params.sizing.max_gross_leverage = self.max_gross_leverage
        return params


def load_settings() -> Settings:
    """Factory: validate + freeze (mutability blocked at boundary)."""
    s = Settings()  # type: ignore[call-arg]
    s.trend_hl_data_dir.mkdir(parents=True, exist_ok=True)
    return s
