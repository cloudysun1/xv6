"""Tenacity-based retry helpers tuned for exchange API behaviour."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from loguru import logger
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

T = TypeVar("T")


class TransientError(Exception):
    """Raised by adapters to opt-in to retry."""


class FatalError(Exception):
    """Never retry."""


async def with_retry(
    func: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 5,
    initial_wait: float = 0.25,
    max_wait: float = 8.0,
    op_name: str = "op",
) -> T:
    """Run an async callable with exponential-backoff jittered retry."""
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_random_exponential(multiplier=initial_wait, max=max_wait),
            retry=retry_if_exception_type(TransientError),
            reraise=True,
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    logger.warning(f"retry[{op_name}] attempt={attempt.retry_state.attempt_number}")
                return await func()
        raise RuntimeError("unreachable")
    except RetryError as e:  # pragma: no cover
        raise TransientError(f"{op_name} exhausted retries") from e
