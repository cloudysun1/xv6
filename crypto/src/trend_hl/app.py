"""Application bootstrap & main asyncio loop.

Wires every layer together. Exposes a Typer CLI with three commands:
``live``, ``paper``, ``backtest``.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from .config.settings import Settings, load_settings
from .core.clock import CLOCK
from .core.enums import RunMode
from .core.event_bus import EventBus
from .core.types import AccountState, Bar, L2Book, SymbolMeta
from .data.bar_aggregator import BarBufferRegistry
from .data.hl_rest_feed import HyperliquidRestFeed
from .data.hl_ws_feed import HyperliquidWsFeed
from .data.store import BarStore
from .exchange.hyperliquid_adapter import HyperliquidAdapter
from .exchange.paper_adapter import PaperAdapter
from .exchange.rate_limiter import RateLimiter
from .execution.executor import Executor
from .monitor.heartbeat import METRICS, heartbeat_loop
from .monitor.notifier import DiscordNotifier, FanoutNotifier, NullNotifier, TelegramNotifier
from .persistence.db import Database
from .strategy.trend_follower import TrendFollower
from .utils.logging import configure_logging

cli = typer.Typer(add_completion=False, help="Trend-HL — Hyperliquid trend-following bot.")


def _build_notifier(settings: Settings):
    notifiers = []
    nc = settings.notifications()
    if nc.telegram_bot_token and nc.telegram_chat_id:
        notifiers.append(TelegramNotifier(
            nc.telegram_bot_token.get_secret_value(), nc.telegram_chat_id,
        ))
    if nc.discord_webhook_url:
        notifiers.append(DiscordNotifier(nc.discord_webhook_url.get_secret_value()))
    if not notifiers:
        return NullNotifier()
    return FanoutNotifier(notifiers)


async def _seed_history(rest: HyperliquidRestFeed, registry: BarBufferRegistry,
                        symbols: list[str], interval: str, n_bars: int = 1500) -> None:
    end_ms = CLOCK.now_ms()
    # 1m bars → ms each
    step_ms_map = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
    step = step_ms_map.get(interval, 60_000)
    start_ms = end_ms - n_bars * step
    for sym in symbols:
        try:
            bars = await rest.fetch_bars(sym, interval, start_ms, end_ms)
            buf = registry.get_or_create(sym, interval)
            await buf.seed(bars)
        except Exception as e:
            logger.warning(f"seed {sym} failed: {e}")


async def _live_or_paper(mode: RunMode) -> None:
    settings = load_settings()
    configure_logging(level=settings.trend_hl_log_level,
                      log_dir=settings.trend_hl_data_dir / "logs")
    logger.info(f"trend-hl starting in {mode.value} mode")

    params = settings.strategy_params()
    universe = settings.load_universe()
    active_symbols = [u.symbol for u in universe.active]

    bus = EventBus()
    stop_event = asyncio.Event()

    # ---- exchange ----
    if mode is RunMode.LIVE:
        adapter = HyperliquidAdapter(settings.hl(), RateLimiter())
        await adapter.connect()
        if params.execution.cancel_all_on_start:
            try:
                n = await adapter.cancel_all()
                logger.info(f"cancelled {n} stale orders on start")
            except Exception as e:
                logger.warning(f"cancel_all failed: {e}")
    else:
        adapter = PaperAdapter(starting_equity=Decimal("10000"))  # type: ignore[assignment]
        await adapter.connect()

    # ---- data feeds ----
    rest = HyperliquidRestFeed(settings.hl_api_url)
    metas: dict[str, SymbolMeta] = {}
    try:
        metas = await rest.fetch_meta()
    except Exception as e:
        logger.warning(f"REST meta failed: {e}")
    if isinstance(adapter, PaperAdapter) and metas:
        adapter.set_meta(metas)

    interval = params.execution.bar_interval
    registry = BarBufferRegistry(max_bars=5000)
    await _seed_history(rest, registry, active_symbols, interval)

    ws = HyperliquidWsFeed(settings.hl_ws_url, bus)
    ws.subscribe_candles(active_symbols, interval)
    ws.subscribe_l2(active_symbols)
    await ws.start()

    bar_sub = bus.subscribe("bar", name="strategy-bars")
    book_sub = bus.subscribe("book", name="strategy-book")
    ctrl_sub = bus.subscribe("control", name="strategy-control")

    notifier = _build_notifier(settings)

    # ---- strategy + executor ----
    strategy = TrendFollower(params, universe)
    strategy.warmup(registry, interval)
    executor = Executor(adapter, params.execution)

    # ---- persistence ----
    db = Database(settings.trend_hl_data_dir / "orders.sqlite")
    await db.connect()

    bar_store = BarStore(settings.trend_hl_data_dir / "bars")

    # ---- background tasks ----
    background = [
        asyncio.create_task(CLOCK.run_forever(stop_event), name="clock"),
        asyncio.create_task(bar_store.run_flusher(stop_event), name="bar-store"),
        asyncio.create_task(heartbeat_loop(bus, notifier, every_s=300, stop_event=stop_event), name="heartbeat"),
    ]

    # most recent book per symbol
    latest_books: dict[str, L2Book] = {}
    last_rebalance_bar: dict[str, int] = {}

    async def _book_consumer() -> None:
        async for ev in bus.stream(book_sub):
            book: L2Book = ev.payload  # type: ignore[assignment]
            latest_books[book.symbol] = book
            if isinstance(adapter, PaperAdapter):
                adapter.update_book(book)

    async def _ctrl_consumer() -> None:
        async for ev in bus.stream(ctrl_sub):
            payload = ev.payload
            if isinstance(payload, dict) and "resync" in payload:
                logger.warning(f"resync requested: {payload['resync']}")
                await _seed_history(rest, registry, payload["resync"], interval, n_bars=300)

    async def _bar_consumer() -> None:
        nonlocal last_rebalance_bar
        bars_per_cycle = params.execution.rebalance_every_n_bars
        async for ev in bus.stream(bar_sub):
            bar: Bar = ev.payload  # type: ignore[assignment]
            buf = registry.get_or_create(bar.symbol, bar.interval)
            new_bar = await buf.upsert(bar)
            if new_bar:
                METRICS.bars_seen += 1
                await bar_store.append(bar)
                # rebalance trigger: every N closed bars on the *primary* symbol
                primary = active_symbols[0]
                if bar.symbol == primary:
                    last = last_rebalance_bar.get(primary, 0)
                    if last + bars_per_cycle <= METRICS.bars_seen:
                        last_rebalance_bar[primary] = METRICS.bars_seen
                        await _rebalance()

    async def _rebalance() -> None:
        try:
            account = await adapter.fetch_account()
        except Exception as e:
            logger.warning(f"fetch_account failed: {e}")
            return
        METRICS.update_equity(account.equity)
        try:
            await db.insert_equity(account)
        except Exception:
            pass

        if not latest_books:
            return

        decision = strategy.step(
            ts_ms=CLOCK.now_ms(), registry=registry, interval=interval,
            account=account, books=latest_books,
            ws_healthy=ws.healthy, clock_drift_ms=CLOCK.state.drift_ms,
        )
        for sig in decision.signals.values():
            METRICS.signals_emitted += 1
            with contextlib.suppress(Exception):
                await db.insert_signal(sig)

        targets = {s: t.target_size for s, t in decision.targets.items()}
        report = await executor.execute_targets(targets, account, latest_books, metas)
        METRICS.orders_submitted += report.submitted
        METRICS.orders_filled += report.filled
        METRICS.orders_rejected += report.rejected

        # log fills (best-effort)
        try:
            since = CLOCK.now_ms() - 5 * 60 * 1000
            fills = await adapter.fetch_recent_fills(since)
            for f in fills:
                with contextlib.suppress(Exception):
                    await db.insert_fill(f)
            METRICS.fills_total += len(fills)
        except Exception:
            pass

    # ---- signal handlers ----
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for s in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(s, stop_event.set)

    consumers = [
        asyncio.create_task(_book_consumer(), name="book-consumer"),
        asyncio.create_task(_ctrl_consumer(), name="ctrl-consumer"),
        asyncio.create_task(_bar_consumer(), name="bar-consumer"),
    ]

    await notifier.send(f"trend-hl started in {mode.value} mode", level="success")

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("shutting down…")
        await ws.stop()
        for t in consumers + background:
            t.cancel()
        await asyncio.gather(*consumers, *background, return_exceptions=True)
        await rest.close()
        await adapter.close()
        await db.close()
        await notifier.send("trend-hl stopped", level="warn")
        await notifier.close()


@cli.command()
def live() -> None:
    """Run with real Hyperliquid execution."""
    asyncio.run(_live_or_paper(RunMode.LIVE))


@cli.command()
def paper() -> None:
    """Run with paper-trading adapter (real market data)."""
    asyncio.run(_live_or_paper(RunMode.PAPER))


@cli.command()
def backtest(
    symbol: str = typer.Option("BTC"),
    interval: str = typer.Option("1m"),
    days: int = typer.Option(7),
) -> None:
    """Run a backtest for a single symbol on cached/REST data."""
    asyncio.run(_run_backtest(symbol, interval, days))


async def _run_backtest(symbol: str, interval: str, days: int) -> None:
    from .backtest.engine import Backtester
    from .backtest.reporter import compute_stats, report_text

    settings = load_settings()
    configure_logging(level=settings.trend_hl_log_level,
                      log_dir=settings.trend_hl_data_dir / "logs")
    rest = HyperliquidRestFeed(settings.hl_api_url)
    end = CLOCK.now_ms()
    start = end - days * 86_400_000
    bars = await rest.fetch_bars(symbol, interval, start, end)
    await rest.close()

    import polars as pl
    df = pl.DataFrame([{
        "open_time_ms": b.open_time_ms, "close_time_ms": b.close_time_ms,
        "open": b.open, "high": b.high, "low": b.low, "close": b.close,
        "volume": b.volume, "n_trades": b.n_trades,
    } for b in bars])
    if df.is_empty():
        logger.error(f"no bars fetched for {symbol}")
        return

    params = settings.strategy_params()
    from .config.settings import Universe, UniverseEntry
    uni = Universe(symbols=[UniverseEntry(symbol=symbol, enabled=True, weight=1.0)])

    bt = Backtester(params, uni, {symbol: df}, starting_equity=Decimal("10000"), interval=interval)
    result = await bt.run()
    stats = compute_stats(result.equity_curve, result.trades, result.fees)
    print(report_text(stats))


if __name__ == "__main__":
    cli()
