"""Notifier abstractions + Telegram/Discord implementations."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

import httpx
from loguru import logger


@runtime_checkable
class INotifier(Protocol):
    async def send(self, message: str, *, level: str = "info") -> bool: ...
    async def close(self) -> None: ...


class NullNotifier:
    async def send(self, message: str, *, level: str = "info") -> bool:  # noqa: ARG002
        return True

    async def close(self) -> None:
        pass


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._client = httpx.AsyncClient(timeout=10.0)

    async def send(self, message: str, *, level: str = "info") -> bool:
        prefix = {"info": "ℹ️", "warn": "⚠️", "error": "🚨", "success": "✅"}.get(level, "")
        text = f"{prefix} {message}"[:4000]
        try:
            r = await self._client.post(self._url, json={
                "chat_id": self._chat_id, "text": text, "parse_mode": "HTML",
            })
            return r.status_code == 200
        except Exception as e:
            logger.warning(f"telegram send failed: {e}")
            return False

    async def close(self) -> None:
        await self._client.aclose()


class DiscordNotifier:
    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url
        self._client = httpx.AsyncClient(timeout=10.0)

    async def send(self, message: str, *, level: str = "info") -> bool:
        prefix = {"info": "[INFO]", "warn": "[WARN]", "error": "[ERROR]", "success": "[OK]"}.get(level, "")
        try:
            r = await self._client.post(self._url, json={"content": f"{prefix} {message}"[:1900]})
            return r.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"discord send failed: {e}")
            return False

    async def close(self) -> None:
        await self._client.aclose()


class FanoutNotifier:
    """Sends to multiple notifiers concurrently."""

    def __init__(self, notifiers: list[INotifier]) -> None:
        self._notifiers = notifiers

    async def send(self, message: str, *, level: str = "info") -> bool:
        if not self._notifiers:
            return True
        results = await asyncio.gather(
            *(n.send(message, level=level) for n in self._notifiers),
            return_exceptions=True,
        )
        return all(r is True for r in results)

    async def close(self) -> None:
        await asyncio.gather(*(n.close() for n in self._notifiers), return_exceptions=True)
