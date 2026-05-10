from __future__ import annotations

import asyncio

import pytest

from trend_hl.core.types import Bar
from trend_hl.data.bar_aggregator import BarBuffer


@pytest.mark.asyncio
async def test_aggregator_upsert_and_dedupe() -> None:
    buf = BarBuffer("BTC", "1m", max_bars=100)
    b1 = Bar("BTC", "1m", 1000, 1060, 1, 2, 0.5, 1.5, 100)
    b1u = Bar("BTC", "1m", 1000, 1060, 1, 3, 0.5, 2.0, 200)  # update same
    b2 = Bar("BTC", "1m", 1060, 1120, 2, 2.5, 1.5, 2.2, 80)
    assert await buf.upsert(b1) is True
    assert await buf.upsert(b1u) is False  # not a new bar
    assert await buf.upsert(b2) is True
    arr = buf.to_numpy()
    assert arr["close"][-1] == 2.2
    assert arr["high"][-2] == 3  # updated value retained


@pytest.mark.asyncio
async def test_aggregator_rejects_out_of_order() -> None:
    buf = BarBuffer("BTC", "1m")
    b2 = Bar("BTC", "1m", 2000, 2060, 1, 1, 1, 1, 1)
    b1 = Bar("BTC", "1m", 1000, 1060, 1, 1, 1, 1, 1)
    assert await buf.upsert(b2) is True
    assert await buf.upsert(b1) is False
    assert len(buf) == 1
