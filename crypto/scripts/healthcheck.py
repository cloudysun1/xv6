#!/usr/bin/env python3
"""Container healthcheck — exits 0 if recent log activity, else 1."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

LOG_FILE = Path(os.environ.get("TREND_HL_DATA_DIR", "./data")) / "logs" / "trend_hl.log"
MAX_AGE_S = int(os.environ.get("HEALTHCHECK_MAX_AGE_S", "180"))

if not LOG_FILE.exists():
    sys.exit(1)
mtime = LOG_FILE.stat().st_mtime
age = time.time() - mtime
sys.exit(0 if age < MAX_AGE_S else 1)
