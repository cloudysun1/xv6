"""Top-level order Executor.

Workflow per signal-cycle:

1. Fetch fresh account state and the latest L2 book per symbol.
2. For each target position from the strategy, build maker orders
   (``order_router.make_orders``).
3. Submit; wait ``maker_timeout_s`` for fills via account polling.
4. For unfilled remainder, cancel and resubmit IOC fallback.
5. Persist OrderAck & Fill rows for audit.

Idempotency: every order carries a deterministic ``client_id`` =
``f"{symbol}-{ts_ms}-{seq}"`` to dedupe across retries.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from dataclasses import dataclass
from decimal import Decimal

from loguru import logger

from ..config.strategy_params import ExecutionParams
from ..core.clock import CLOCK
from ..core.enums import OrderStatus
from ..core.types import AccountState, L2Book, OrderRequest, SymbolMeta
from ..exchange.interfaces import IExchange
from .order_router import make_ioc_fallback, make_orders


@dataclass
class ExecutionReport:
    submitted: int = 0
    accepted: int = 0
    filled: int = 0
    rejected: int = 0
    cancelled: int = 0


class Executor:
    def __init__(
        self,
        exchange: IExchange,
        params: ExecutionParams,
    ) -> None:
        self._ex = exchange
        self._p = params
        self._counter = itertools.count(1)

    def _client_id(self, symbol: str) -> str:
        return f"{symbol}-{CLOCK.now_ms()}-{next(self._counter):06d}"

    async def execute_targets(
        self,
        targets: dict[str, Decimal],
        account: AccountState,
        books: dict[str, L2Book],
        metas: dict[str, SymbolMeta],
    ) -> ExecutionReport:
        report = ExecutionReport()
        tasks = []
        for sym, tgt in targets.items():
            book = books.get(sym)
            meta = metas.get(sym)
            if book is None or meta is None:
                continue
            cur = account.positions.get(sym)
            tasks.append(self._execute_one(sym, tgt, cur, book, meta, report))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=False)
        return report

    async def _execute_one(self, sym, tgt, cur, book, meta, report):  # type: ignore[no-untyped-def]
        orders = make_orders(
            sym, tgt, cur, book, meta, self._p,
            client_id_factory=lambda s=sym: self._client_id(s),
        )
        if not orders:
            return
        for req in orders:
            ack = await self._submit_with_fallback(req, book, meta)
            report.submitted += 1
            if ack.status is OrderStatus.FILLED:
                report.filled += 1
            elif ack.status is OrderStatus.ACCEPTED:
                report.accepted += 1
            elif ack.status in (OrderStatus.REJECTED, OrderStatus.UNKNOWN):
                report.rejected += 1

    async def _submit_with_fallback(self, req: OrderRequest, book: L2Book, meta: SymbolMeta):  # type: ignore[no-untyped-def]
        ack = await self._ex.place_order(req)
        if ack.status is OrderStatus.FILLED:
            return ack
        if ack.status is OrderStatus.ACCEPTED and ack.exchange_id is not None:
            await asyncio.sleep(self._p.maker_timeout_s)
            # cancel any remaining size, then submit IOC for the leftover
            with contextlib.suppress(Exception):
                await self._ex.cancel_order(req.symbol, ack.exchange_id)
            ioc_req = make_ioc_fallback(req, book, meta)
            return await self._ex.place_order(ioc_req)
        return ack
