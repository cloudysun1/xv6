from __future__ import annotations

import asyncio

import pytest

from trend_hl.exchange.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_throttles() -> None:
    rl = RateLimiter({"x": (3.0, 3.0)})  # 3 tokens, refill 3/s
    t = asyncio.get_event_loop().time()
    for _ in range(3):
        await rl.acquire("x")
    elapsed = asyncio.get_event_loop().time() - t
    assert elapsed < 0.05

    # 4th request should wait ~0.33s
    t2 = asyncio.get_event_loop().time()
    await rl.acquire("x")
    elapsed2 = asyncio.get_event_loop().time() - t2
    assert elapsed2 > 0.1


@pytest.mark.asyncio
async def test_rate_limiter_unknown_category() -> None:
    rl = RateLimiter({"a": (5.0, 5.0)})
    with pytest.raises(KeyError):
        await rl.acquire("missing")
