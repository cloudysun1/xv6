"""In-memory paper-trading adapter — realistic enough for live dry-runs.

Implements ``IExchange``. Latency, partial fills and slippage are modelled in
:mod:`backtest.slippage_model`; for paper mode we apply mid + 1 tick slippage
on market/IOC orders and treat post-only orders as immediately resting.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from decimal import Decimal
from typing import Any

from loguru import logger

from ..core.clock import CLOCK
from ..core.enums import OrderSide, OrderStatus, OrderType
from ..core.types import AccountState, Fill, L2Book, OrderAck, OrderRequest, Position, SymbolMeta


class PaperAdapter:
    def __init__(self, starting_equity: Decimal = Decimal("10000")) -> None:
        self._equity = starting_equity
        self._positions: dict[str, Position] = {}
        self._meta: dict[str, SymbolMeta] = {}
        self._fills: list[Fill] = []
        self._counter = itertools.count(1)
        self._books: dict[str, L2Book] = {}
        self._lock = asyncio.Lock()
        self._fill_callbacks: list[Any] = []

    async def connect(self) -> None:
        logger.info(f"PaperAdapter ready (equity={self._equity})")

    async def close(self) -> None:
        pass

    def set_meta(self, meta: dict[str, SymbolMeta]) -> None:
        self._meta = meta

    def update_book(self, book: L2Book) -> None:
        self._books[book.symbol] = book

    async def fetch_meta(self) -> dict[str, SymbolMeta]:
        return self._meta

    async def fetch_account(self) -> AccountState:
        margin_used = sum(
            (abs(p.size) * p.entry_price for p in self._positions.values()),
            start=Decimal(0),
        )
        return AccountState(
            ts_ms=CLOCK.now_ms(),
            equity=self._equity,
            margin_used=margin_used,
            free_margin=self._equity - margin_used,
            positions=dict(self._positions),
        )

    async def place_order(self, req: OrderRequest) -> OrderAck:
        async with self._lock:
            book = self._books.get(req.symbol)
            if book is None:
                return OrderAck(client_id=req.client_id, exchange_id=None,
                                status=OrderStatus.REJECTED, raw={"err": "no_book"})
            mid = Decimal(str(book.mid))
            tick_buffer = Decimal("0.0001") * mid
            if req.order_type is OrderType.MARKET or (req.order_type is OrderType.LIMIT and not req.post_only):
                fill_px = (mid + tick_buffer) if req.side is OrderSide.BUY else (mid - tick_buffer)
                self._apply_fill(req.symbol, req.side, req.size, fill_px, req.client_id)
                ex_id = next(self._counter)
                return OrderAck(client_id=req.client_id, exchange_id=ex_id,
                                status=OrderStatus.FILLED, raw={"px": str(fill_px)})
            # Post-only — assume rests at requested price
            ex_id = next(self._counter)
            return OrderAck(client_id=req.client_id, exchange_id=ex_id,
                            status=OrderStatus.ACCEPTED, raw={})

    def _apply_fill(self, symbol: str, side: OrderSide, size: Decimal, px: Decimal, client_id: str | None) -> None:
        signed = size if side is OrderSide.BUY else -size
        existing = self._positions.get(symbol)
        if existing is None or existing.is_flat:
            new_size = signed
            new_entry = px
        else:
            net = existing.size + signed
            if existing.size * net < 0:
                # crossed through zero — realize old, open new
                realized = (px - existing.entry_price) * existing.size
                self._equity += realized
                new_size = net
                new_entry = px
            elif net == 0:
                realized = (px - existing.entry_price) * existing.size
                self._equity += realized
                new_size = Decimal(0)
                new_entry = Decimal(0)
            else:
                # adding to existing
                if abs(net) > abs(existing.size):
                    # average up
                    new_entry = (existing.entry_price * abs(existing.size) + px * abs(signed)) / abs(net)
                else:
                    realized = (px - existing.entry_price) * (-(net - existing.size))
                    self._equity += realized
                    new_entry = existing.entry_price
                new_size = net

        self._positions[symbol] = Position(
            symbol=symbol, size=new_size, entry_price=new_entry,
            unrealized_pnl=Decimal(0), leverage=1.0,
        )
        fee = abs(size) * px * Decimal("0.0003")  # ~3bps taker
        self._equity -= fee
        self._fills.append(Fill(
            symbol=symbol, ts_ms=CLOCK.now_ms(), side=side,
            price=px, size=size, fee=fee, exchange_id=next(self._counter), client_id=client_id,
        ))

    async def cancel_order(self, symbol: str, exchange_id: str | int) -> bool:
        return True

    async def cancel_all(self, symbol: str | None = None) -> int:
        return 0

    async def fetch_recent_fills(self, since_ms: int) -> list[Fill]:
        return [f for f in self._fills if f.ts_ms >= since_ms]
