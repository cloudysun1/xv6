from __future__ import annotations

from decimal import Decimal

from trend_hl.core.types import SymbolMeta
from trend_hl.exchange.precision import round_price, round_size, slippage_buffer


META = SymbolMeta(symbol="BTC", sz_decimals=4, px_decimals=2,
                  max_leverage=20, min_size=Decimal("0.0001"))


def test_round_size_floors() -> None:
    assert round_size(Decimal("0.12345678"), META) == Decimal("0.1234")
    assert round_size(Decimal("-0.00009"), META) == Decimal(0)
    assert round_size(Decimal("0"), META) == Decimal(0)


def test_round_price_5sigfig() -> None:
    px = round_price(Decimal("12345.6789"), META)
    assert str(px) in ("12345", "12346", "12345.0")


def test_slippage_buffer() -> None:
    buf = slippage_buffer(Decimal("100"), META, ticks=3)
    assert buf == Decimal("0.03")
