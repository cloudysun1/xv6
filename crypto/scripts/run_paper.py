#!/usr/bin/env python3
"""Paper-trade entry-point (real market data, simulated fills)."""

from __future__ import annotations

import sys

from trend_hl.app import cli

if __name__ == "__main__":
    sys.argv.insert(1, "paper")
    cli()
