"""Hyperliquid tick & lot precision rounding.

Rules (Hyperliquid perps as of 2024-2025):

* Sizes are rounded DOWN to ``sz_decimals`` from ``meta``.
* Prices use **5 significant figures** with the additional constraint
  ``px_decimals = 6 - sz_decimals`` for perps. Any extra precision is rejected.

These helpers are pure ``Decimal`` math — no float drift.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, getcontext

from ..core.types import SymbolMeta

getcontext().prec = 28

_FIVE_SIG = Decimal("0.00001")  # used for normalization helpers


def round_size(size: Decimal, meta: SymbolMeta) -> Decimal:
    """Round absolute size DOWN to lot. Sign is preserved."""
    if size == 0:
        return size
    q = Decimal(10) ** -meta.sz_decimals
    abs_q = abs(size).quantize(q, rounding=ROUND_DOWN)
    if abs_q < meta.min_size:
        return Decimal(0)
    return abs_q if size > 0 else -abs_q


def round_price(price: Decimal, meta: SymbolMeta, side_for_passive: str | None = None) -> Decimal:
    """Round price to HL constraints: max(5 sig figs, px_decimals)."""
    if price <= 0:
        raise ValueError("price must be > 0")
    # 5 significant figures
    s = f"{price:.10E}"
    mantissa, exp = s.split("E")
    mantissa_d = Decimal(mantissa).quantize(Decimal("1.0000"), rounding=ROUND_HALF_EVEN)
    five_sig = (mantissa_d * (Decimal(10) ** int(exp))).normalize()

    # px_decimals constraint
    px_q = Decimal(10) ** -meta.px_decimals
    decimals_q = price.quantize(px_q, rounding=ROUND_HALF_EVEN)

    # take the *less precise* of the two — both must be satisfied
    candidate = max(five_sig.as_tuple().exponent, decimals_q.as_tuple().exponent)  # type: ignore[arg-type]
    final_q = Decimal(10) ** Decimal(candidate)
    rounded = price.quantize(final_q, rounding=ROUND_HALF_EVEN)

    # For passive orders, ensure we don't cross by accident
    if side_for_passive == "buy":
        if rounded > price:
            rounded -= final_q
    elif side_for_passive == "sell":
        if rounded < price:
            rounded += final_q
    return rounded.normalize()


def slippage_buffer(price: Decimal, meta: SymbolMeta, ticks: int) -> Decimal:
    """Return |price increment| of ``ticks`` smallest units."""
    return (Decimal(10) ** -meta.px_decimals) * Decimal(ticks)
