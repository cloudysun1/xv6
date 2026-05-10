"""Domain types and immutable data containers used across the system.

All numeric quantities use ``Decimal`` at boundary layers (orders, fills, prices)
to avoid float drift, and ``float`` only inside the signal/risk math layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from .enums import OrderSide, OrderStatus, OrderType, SignalDirection, TimeInForce

Symbol = str  # e.g. "BTC", "ETH" — Hyperliquid uses bare coin symbols.


@dataclass(slots=True, frozen=True)
class Bar:
    """OHLCV bar in UTC."""

    symbol: Symbol
    interval: str  # "1m" | "5m" | "15m" | "1h"
    open_time_ms: int  # UTC ms
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    n_trades: int = 0


@dataclass(slots=True, frozen=True)
class L2Level:
    price: float
    size: float


@dataclass(slots=True, frozen=True)
class L2Book:
    symbol: Symbol
    ts_ms: int
    bids: tuple[L2Level, ...]
    asks: tuple[L2Level, ...]

    @property
    def mid(self) -> float:
        if not self.bids or not self.asks:
            raise ValueError("Empty book")
        return 0.5 * (self.bids[0].price + self.asks[0].price)

    @property
    def spread_bps(self) -> float:
        b, a = self.bids[0].price, self.asks[0].price
        return (a - b) / (0.5 * (a + b)) * 1e4


@dataclass(slots=True, frozen=True)
class Trade:
    symbol: Symbol
    ts_ms: int
    price: float
    size: float
    side: OrderSide  # aggressor side


@dataclass(slots=True, frozen=True)
class Signal:
    symbol: Symbol
    ts_ms: int
    direction: SignalDirection
    strength: float  # in [-1, 1] continuous
    target_leverage: float  # signed, e.g. +0.7 means 70% long
    metadata: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OrderRequest:
    symbol: Symbol
    side: OrderSide
    size: Decimal
    order_type: OrderType
    price: Decimal | None  # None for market
    tif: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    post_only: bool = False
    client_id: str | None = None  # for idempotency


@dataclass(slots=True, frozen=True)
class OrderAck:
    client_id: str | None
    exchange_id: str | int | None
    status: OrderStatus
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class Fill:
    symbol: Symbol
    ts_ms: int
    side: OrderSide
    price: Decimal
    size: Decimal
    fee: Decimal
    exchange_id: str | int | None
    client_id: str | None


@dataclass(slots=True, frozen=True)
class Position:
    symbol: Symbol
    size: Decimal  # signed; positive=long, negative=short
    entry_price: Decimal
    unrealized_pnl: Decimal
    leverage: float
    liquidation_price: Decimal | None = None

    @property
    def is_flat(self) -> bool:
        return self.size == Decimal(0)


@dataclass(slots=True, frozen=True)
class AccountState:
    ts_ms: int
    equity: Decimal
    margin_used: Decimal
    free_margin: Decimal
    positions: dict[Symbol, Position]


@dataclass(slots=True, frozen=True)
class SymbolMeta:
    """Per-asset trading constraints from Hyperliquid `meta` endpoint."""

    symbol: Symbol
    sz_decimals: int  # lot precision
    px_decimals: int  # tick precision (derived; HL uses 5 sig figs rule)
    max_leverage: int
    min_size: Decimal


# Event-bus payloads --------------------------------------------------------

EventKind = Literal[
    "bar",
    "trade",
    "book",
    "signal",
    "order_request",
    "order_ack",
    "fill",
    "account",
    "heartbeat",
    "control",
]


@dataclass(slots=True, frozen=True)
class Event:
    kind: EventKind
    ts_ms: int
    payload: object
