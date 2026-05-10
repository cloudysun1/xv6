"""Hyperliquid exchange adapter — wraps the official ``hyperliquid-python-sdk``.

Responsibilities
----------------
* Build the ``eth_account`` LocalAccount from the Agent wallet private key.
* Construct ``Info`` and ``Exchange`` clients pinned to the configured URL.
* Translate our domain ``OrderRequest`` ↔ HL's ``order_type`` dicts.
* Apply tick / lot precision rounding before submitting.
* Respect the rate limiter and wrap every call in retry.
* Map HL's response shape into ``OrderAck`` / ``Fill`` / ``AccountState``.

We deliberately keep this thin — strategy/risk logic must NEVER reach in.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from eth_account import Account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange  # type: ignore[import-untyped]
from hyperliquid.info import Info  # type: ignore[import-untyped]
from loguru import logger

from ..config.settings import HyperliquidCreds
from ..core.clock import CLOCK
from ..core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from ..core.types import AccountState, Fill, OrderAck, OrderRequest, Position, SymbolMeta
from ..utils.retry import TransientError, with_retry
from .precision import round_price, round_size
from .rate_limiter import RateLimiter


class HyperliquidAdapter:
    def __init__(self, creds: HyperliquidCreds, limiter: RateLimiter | None = None) -> None:
        self._creds = creds
        self._limiter = limiter or RateLimiter()
        self._wallet: LocalAccount | None = None
        self._info: Info | None = None
        self._exchange: Exchange | None = None
        self._meta: dict[str, SymbolMeta] = {}
        self._lock = asyncio.Lock()

    # ----------------- lifecycle -----------------
    async def connect(self) -> None:
        async with self._lock:
            if self._exchange is not None:
                return
            pk = self._creds.api_secret.get_secret_value()
            self._wallet = Account.from_key(pk)
            agent_addr = self._wallet.address
            owner_addr = self._creds.account_address
            logger.info(f"HL adapter: agent={agent_addr[:6]}… owner={owner_addr[:6]}…")
            # Both clients are sync HTTP; we wrap calls via run_in_executor.
            self._info = Info(self._creds.api_url, skip_ws=True)
            self._exchange = Exchange(
                wallet=self._wallet,
                base_url=self._creds.api_url,
                account_address=owner_addr,
            )
            await self._refresh_meta()

    async def close(self) -> None:
        # SDK Info uses requests Session under the hood; nothing async to close.
        self._info = None
        self._exchange = None
        self._wallet = None

    async def _to_thread(self, fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    # ----------------- meta -----------------
    async def _refresh_meta(self) -> None:
        assert self._info is not None
        await self._limiter.acquire("info", weight=1.0)
        try:
            data = await self._to_thread(self._info.meta)
        except Exception as e:
            raise TransientError(f"meta failed: {e}") from e
        out: dict[str, SymbolMeta] = {}
        for u in data.get("universe", []):
            sym = u["name"]
            sz_dec = int(u.get("szDecimals", 0))
            max_lev = int(u.get("maxLeverage", 1))
            min_size = Decimal(1) / (Decimal(10) ** sz_dec) if sz_dec > 0 else Decimal(1)
            out[sym] = SymbolMeta(
                symbol=sym, sz_decimals=sz_dec, px_decimals=6 - sz_dec,
                max_leverage=max_lev, min_size=min_size,
            )
        self._meta = out
        logger.info(f"HL meta refreshed: {len(out)} perps")

    async def fetch_meta(self) -> dict[str, SymbolMeta]:
        if not self._meta:
            await self._refresh_meta()
        return self._meta

    # ----------------- account -----------------
    async def fetch_account(self) -> AccountState:
        assert self._info is not None
        await self._limiter.acquire("info")

        async def _do() -> dict[str, Any]:
            try:
                return await self._to_thread(self._info.user_state, self._creds.account_address)
            except Exception as e:
                raise TransientError(str(e)) from e

        data = await with_retry(_do, op_name="user_state")

        margin = data.get("marginSummary", {}) or data.get("crossMarginSummary", {})
        equity = Decimal(str(margin.get("accountValue", "0")))
        margin_used = Decimal(str(margin.get("totalMarginUsed", "0")))
        free_margin = equity - margin_used

        positions: dict[str, Position] = {}
        for p in data.get("assetPositions", []):
            pos = p.get("position", {})
            coin = pos.get("coin")
            if coin is None:
                continue
            sz = Decimal(str(pos.get("szi", "0")))
            entry = Decimal(str(pos.get("entryPx", "0") or "0"))
            upnl = Decimal(str(pos.get("unrealizedPnl", "0") or "0"))
            lev = float(pos.get("leverage", {}).get("value", 1))
            liq_raw = pos.get("liquidationPx")
            liq = Decimal(str(liq_raw)) if liq_raw not in (None, "0", "") else None
            positions[coin] = Position(
                symbol=coin, size=sz, entry_price=entry,
                unrealized_pnl=upnl, leverage=lev, liquidation_price=liq,
            )
        return AccountState(
            ts_ms=CLOCK.now_ms(), equity=equity, margin_used=margin_used,
            free_margin=free_margin, positions=positions,
        )

    # ----------------- orders -----------------
    async def place_order(self, req: OrderRequest) -> OrderAck:
        assert self._exchange is not None
        meta = (await self.fetch_meta()).get(req.symbol)
        if meta is None:
            return OrderAck(client_id=req.client_id, exchange_id=None,
                            status=OrderStatus.REJECTED, raw={"err": f"unknown_symbol:{req.symbol}"})

        size = round_size(req.size, meta)
        if size == 0:
            return OrderAck(client_id=req.client_id, exchange_id=None,
                            status=OrderStatus.REJECTED, raw={"err": "size_below_min"})

        is_buy = req.side is OrderSide.BUY
        if req.order_type is OrderType.LIMIT:
            if req.price is None:
                return OrderAck(client_id=req.client_id, exchange_id=None,
                                status=OrderStatus.REJECTED, raw={"err": "limit_price_missing"})
            px = round_price(req.price, meta, side_for_passive=req.side.value if req.post_only else None)
            tif = "Alo" if req.post_only else req.tif.value
            order_type_payload = {"limit": {"tif": tif}}
            order_px: float = float(px)
        else:
            order_type_payload = {"limit": {"tif": "Ioc"}}  # HL has no true market
            # use far-off price for IOC market replacement
            order_px = float(req.price) if req.price else 0.0

        await self._limiter.acquire("exchange")

        async def _do() -> dict[str, Any]:
            try:
                return await self._to_thread(
                    self._exchange.order,
                    req.symbol, is_buy, float(abs(size)), order_px,
                    order_type_payload, req.reduce_only, req.client_id,
                )
            except Exception as e:
                raise TransientError(str(e)) from e

        try:
            resp = await with_retry(_do, op_name="place_order", max_attempts=3)
        except Exception as e:
            logger.error(f"place_order fatal: {e}")
            return OrderAck(client_id=req.client_id, exchange_id=None,
                            status=OrderStatus.REJECTED, raw={"err": str(e)})

        return self._parse_order_response(resp, req)

    @staticmethod
    def _parse_order_response(resp: dict[str, Any], req: OrderRequest) -> OrderAck:
        status_str = resp.get("status")
        data = resp.get("response", {}).get("data", {}) if isinstance(resp.get("response"), dict) else {}
        statuses = data.get("statuses", []) if isinstance(data, dict) else []
        ex_id: str | int | None = None
        ord_status = OrderStatus.UNKNOWN
        if statuses:
            s0 = statuses[0]
            if isinstance(s0, dict):
                if "resting" in s0:
                    ex_id = s0["resting"].get("oid")
                    ord_status = OrderStatus.ACCEPTED
                elif "filled" in s0:
                    ex_id = s0["filled"].get("oid")
                    ord_status = OrderStatus.FILLED
                elif "error" in s0:
                    ord_status = OrderStatus.REJECTED
        if status_str == "err":
            ord_status = OrderStatus.REJECTED
        return OrderAck(client_id=req.client_id, exchange_id=ex_id, status=ord_status, raw=resp)

    async def cancel_order(self, symbol: str, exchange_id: str | int) -> bool:
        assert self._exchange is not None
        await self._limiter.acquire("exchange")
        try:
            resp = await self._to_thread(self._exchange.cancel, symbol, int(exchange_id))
            return resp.get("status") == "ok"
        except Exception as e:
            logger.warning(f"cancel_order failed: {e}")
            return False

    async def cancel_all(self, symbol: str | None = None) -> int:
        assert self._exchange is not None and self._info is not None
        await self._limiter.acquire("info")
        opens = await self._to_thread(self._info.open_orders, self._creds.account_address)
        targets = [o for o in opens if symbol is None or o.get("coin") == symbol]
        n = 0
        for o in targets:
            ok = await self.cancel_order(o["coin"], o["oid"])
            if ok:
                n += 1
        return n

    async def fetch_recent_fills(self, since_ms: int) -> list[Fill]:
        assert self._info is not None
        await self._limiter.acquire("info")
        try:
            res = await self._to_thread(
                self._info.user_fills_by_time,
                self._creds.account_address, since_ms,
            )
        except Exception:
            res = await self._to_thread(self._info.user_fills, self._creds.account_address)

        out: list[Fill] = []
        for f in res or []:
            try:
                side = OrderSide.BUY if f.get("side") in ("B", "buy", True) else OrderSide.SELL
                out.append(Fill(
                    symbol=f["coin"],
                    ts_ms=int(f.get("time", 0)),
                    side=side,
                    price=Decimal(str(f["px"])),
                    size=Decimal(str(f["sz"])),
                    fee=Decimal(str(f.get("fee", "0"))),
                    exchange_id=f.get("oid"),
                    client_id=f.get("cloid"),
                ))
            except Exception as e:
                logger.warning(f"bad fill row: {e} :: {f}")
        return out
