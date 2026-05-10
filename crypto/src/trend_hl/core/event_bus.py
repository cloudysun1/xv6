"""Asyncio event-bus with bounded back-pressure and topic fan-out.

Each topic owns an :class:`asyncio.Queue`. Producers ``publish`` non-blockingly;
when a queue is full we drop the *oldest* message and increment a metric so the
slow consumer becomes visible without stalling market-data ingestion. Critical
topics (``order_request``, ``fill``) use unbounded queues to never lose state.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import AsyncIterator

from loguru import logger

from .types import Event, EventKind

LOSSY_TOPICS: frozenset[EventKind] = frozenset({"bar", "trade", "book", "heartbeat"})
RELIABLE_TOPICS: frozenset[EventKind] = frozenset({"signal", "order_request", "order_ack", "fill", "account", "control"})


@dataclass
class TopicStats:
    published: int = 0
    delivered: int = 0
    dropped: int = 0
    subscribers: int = 0


@dataclass
class _Subscription:
    topic: EventKind
    queue: asyncio.Queue[Event]
    name: str = "anon"
    closed: bool = False


class EventBus:
    """Topic-based async event bus with per-topic subscriptions."""

    def __init__(self, lossy_maxsize: int = 4096, reliable_maxsize: int = 0) -> None:
        self._lossy_maxsize = lossy_maxsize
        self._reliable_maxsize = reliable_maxsize  # 0 = unbounded
        self._subs: dict[EventKind, list[_Subscription]] = defaultdict(list)
        self._stats: dict[EventKind, TopicStats] = defaultdict(TopicStats)
        self._lock = asyncio.Lock()

    def subscribe(self, topic: EventKind, name: str = "anon") -> _Subscription:
        maxsize = self._lossy_maxsize if topic in LOSSY_TOPICS else self._reliable_maxsize
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        sub = _Subscription(topic=topic, queue=q, name=name)
        self._subs[topic].append(sub)
        self._stats[topic].subscribers = len(self._subs[topic])
        logger.debug(f"EventBus: '{name}' subscribed to '{topic}' (maxsize={maxsize})")
        return sub

    async def unsubscribe(self, sub: _Subscription) -> None:
        sub.closed = True
        async with self._lock:
            if sub in self._subs[sub.topic]:
                self._subs[sub.topic].remove(sub)
                self._stats[sub.topic].subscribers = len(self._subs[sub.topic])

    def publish(self, event: Event) -> None:
        topic = event.kind
        stats = self._stats[topic]
        stats.published += 1
        for sub in self._subs[topic]:
            if sub.closed:
                continue
            try:
                sub.queue.put_nowait(event)
                stats.delivered += 1
            except asyncio.QueueFull:
                # Lossy: drop oldest, push new.
                try:
                    _ = sub.queue.get_nowait()
                    sub.queue.put_nowait(event)
                    stats.dropped += 1
                    if stats.dropped % 1000 == 1:
                        logger.warning(
                            f"EventBus: subscriber '{sub.name}' on '{topic}' is slow; "
                            f"dropped={stats.dropped}"
                        )
                except Exception as e:  # pragma: no cover
                    logger.error(f"EventBus drop-replace failed on '{topic}': {e}")

    async def stream(self, sub: _Subscription) -> AsyncIterator[Event]:
        """Yield events for a subscription until it is closed."""
        while not sub.closed:
            try:
                ev = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
                yield ev
            except asyncio.TimeoutError:
                continue

    def stats(self, topic: EventKind) -> TopicStats:
        return self._stats[topic]

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            t: {"published": s.published, "delivered": s.delivered, "dropped": s.dropped, "subscribers": s.subscribers}
            for t, s in self._stats.items()
        }
