#!/usr/bin/env python3
"""Backtest entry-point.

Usage:
    python scripts/run_backtest.py --symbol BTC --interval 1m --days 14
"""

from __future__ import annotations

from trend_hl.app import cli

if __name__ == "__main__":
    cli()
