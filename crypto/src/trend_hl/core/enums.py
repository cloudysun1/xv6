"""Enumerations used across the system."""

from __future__ import annotations

from enum import Enum


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is OrderSide.BUY else -1

    @classmethod
    def from_sign(cls, s: int) -> "OrderSide":
        return cls.BUY if s > 0 else cls.SELL


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    GTC = "Gtc"
    IOC = "Ioc"
    ALO = "Alo"  # Add-Liquidity-Only (post-only) — Hyperliquid name


class OrderStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class SignalDirection(int, Enum):
    LONG = 1
    FLAT = 0
    SHORT = -1


class Regime(str, Enum):
    TRENDING_UP = "trend_up"
    TRENDING_DOWN = "trend_down"
    RANGING = "range"
    CHOP = "chop"


class RunMode(str, Enum):
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"
