"""SQLite persistence for orders, fills, equity snapshots."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import aiosqlite
from loguru import logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    client_id TEXT PRIMARY KEY,
    exchange_id TEXT,
    ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size TEXT NOT NULL,
    price TEXT,
    order_type TEXT NOT NULL,
    tif TEXT,
    post_only INTEGER NOT NULL,
    reduce_only INTEGER NOT NULL,
    status TEXT NOT NULL,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_ts ON orders(ts_ms);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    fee TEXT NOT NULL,
    exchange_id TEXT,
    client_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_fills_ts ON fills(ts_ms);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts_ms INTEGER PRIMARY KEY,
    equity TEXT NOT NULL,
    margin_used TEXT NOT NULL,
    free_margin TEXT NOT NULL,
    positions_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    direction INTEGER NOT NULL,
    strength REAL NOT NULL,
    target_leverage REAL NOT NULL,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_signals_ts ON signals_log(ts_ms);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info(f"sqlite connected: {self._path}")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def insert_order(self, req, ack) -> None:  # type: ignore[no-untyped-def]
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                req.client_id, str(ack.exchange_id) if ack.exchange_id is not None else None,
                int(__import__("time").time() * 1000),
                req.symbol, req.side.value, str(req.size),
                str(req.price) if req.price is not None else None,
                req.order_type.value, req.tif.value,
                int(req.post_only), int(req.reduce_only),
                ack.status.value, json.dumps(ack.raw, default=str),
            ),
        )
        await self._conn.commit()

    async def insert_fill(self, fill) -> None:  # type: ignore[no-untyped-def]
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO fills (ts_ms,symbol,side,price,size,fee,exchange_id,client_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (fill.ts_ms, fill.symbol, fill.side.value, str(fill.price),
             str(fill.size), str(fill.fee),
             str(fill.exchange_id) if fill.exchange_id is not None else None,
             fill.client_id),
        )
        await self._conn.commit()

    async def insert_equity(self, account) -> None:  # type: ignore[no-untyped-def]
        assert self._conn is not None
        positions = {
            sym: {"size": str(p.size), "entry": str(p.entry_price)}
            for sym, p in account.positions.items()
        }
        await self._conn.execute(
            "INSERT OR REPLACE INTO equity_snapshots VALUES (?,?,?,?,?)",
            (account.ts_ms, str(account.equity), str(account.margin_used),
             str(account.free_margin), json.dumps(positions)),
        )
        await self._conn.commit()

    async def insert_signal(self, sig) -> None:  # type: ignore[no-untyped-def]
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO signals_log (ts_ms,symbol,direction,strength,target_leverage,metadata_json) "
            "VALUES (?,?,?,?,?,?)",
            (sig.ts_ms, sig.symbol, int(sig.direction.value),
             float(sig.strength), float(sig.target_leverage),
             json.dumps(sig.metadata, default=str)),
        )
        await self._conn.commit()
