"""Order router: convert TargetPosition delta → OrderRequest list.

Splits big deltas to respect ``slice_max_pct_of_book`` and prefers post-only
maker orders with IOC fallback.
"""

from __future__ import annotations

from decimal import Decimal

from loguru import logger

from ..config.strategy_params import ExecutionParams
from ..core.enums import OrderSide, OrderType, TimeInForce
from ..core.types import L2Book, OrderRequest, Position, SymbolMeta
from ..exchange.precision import round_price, round_size, slippage_buffer


def compute_delta(target: Decimal, current: Decimal) -> Decimal:
    return target - current


def book_depth_size(book: L2Book, side: OrderSide, levels: int = 5) -> Decimal:
    arr = book.asks if side is OrderSide.BUY else book.bids
    return Decimal(str(sum(level.size for level in arr[:levels])))


def make_orders(
    symbol: str,
    target_size: Decimal,
    current: Position | None,
    book: L2Book,
    meta: SymbolMeta,
    params: ExecutionParams,
    client_id_factory,
) -> list[OrderRequest]:
    cur_size = current.size if current else Decimal(0)
    delta = compute_delta(target_size, cur_size)
    delta = round_size(delta, meta)
    if delta == 0:
        return []

    side = OrderSide.BUY if delta > 0 else OrderSide.SELL
    abs_delta = abs(delta)

    # cap by book depth slice
    depth = book_depth_size(book, side, levels=5)
    if depth > 0:
        max_slice = depth * Decimal(str(params.slice_max_pct_of_book))
        max_slice = round_size(max_slice, meta)
    else:
        max_slice = abs_delta

    # reduce_only when shrinking same-side position toward 0 (or flipping past 0)
    reduce_only = False
    if current is not None and current.size != 0:
        if (current.size > 0 and delta < 0 and abs_delta <= current.size) or \
           (current.size < 0 and delta > 0 and abs_delta <= -current.size):
            reduce_only = True

    # passive maker price
    bbo = book.bids[0].price if side is OrderSide.BUY else book.asks[0].price
    px = Decimal(str(bbo))
    px += -slippage_buffer(px, meta, params.maker_offset_ticks) if side is OrderSide.BUY \
        else slippage_buffer(px, meta, params.maker_offset_ticks)
    px = round_price(px, meta, side_for_passive=side.value)

    orders: list[OrderRequest] = []
    remaining = abs_delta
    while remaining > 0:
        chunk = min(remaining, max_slice) if max_slice > 0 else remaining
        chunk = round_size(chunk, meta)
        if chunk <= 0:
            break
        orders.append(OrderRequest(
            symbol=symbol, side=side, size=chunk,
            order_type=OrderType.LIMIT, price=px,
            tif=TimeInForce.ALO, post_only=True, reduce_only=reduce_only,
            client_id=client_id_factory(),
        ))
        remaining -= chunk
        if max_slice <= 0:
            break

    if not orders:
        logger.debug(f"[{symbol}] no orders generated (delta={delta} depth={depth})")
    return orders


def make_ioc_fallback(req: OrderRequest, book: L2Book, meta: SymbolMeta) -> OrderRequest:
    """Take-liquidity fallback if maker doesn't fill in time."""
    bbo = book.asks[0].price if req.side is OrderSide.BUY else book.bids[0].price
    aggressive_px = Decimal(str(bbo))
    aggressive_px += slippage_buffer(aggressive_px, meta, 5) if req.side is OrderSide.BUY \
        else -slippage_buffer(aggressive_px, meta, 5)
    aggressive_px = round_price(aggressive_px, meta)
    return OrderRequest(
        symbol=req.symbol, side=req.side, size=req.size,
        order_type=OrderType.LIMIT, price=aggressive_px,
        tif=TimeInForce.IOC, post_only=False, reduce_only=req.reduce_only,
        client_id=(req.client_id + "-ioc") if req.client_id else None,
    )
