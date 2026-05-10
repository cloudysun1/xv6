#!/usr/bin/env python3
"""Live trading entry-point. Just delegates to ``trend_hl.app``."""

from __future__ import annotations

import sys

from trend_hl.app import cli

if __name__ == "__main__":
    sys.argv.insert(1, "live")
    cli()
