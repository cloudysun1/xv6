"""Loguru configuration with secret redaction and JSON sink for prod."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from loguru import logger

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"0x[a-fA-F0-9]{64}"),  # private keys
    re.compile(r"(?i)(api[_-]?secret|private[_-]?key|bearer)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(telegram|discord)[^=]*[=:]\s*\S+"),
)


def _redact(message: str) -> str:
    out = message
    for pat in _SECRET_PATTERNS:
        out = pat.sub("***REDACTED***", out)
    return out


def _redaction_filter(record: dict[str, Any]) -> bool:
    record["message"] = _redact(str(record["message"]))
    return True


def _json_sink(message: Any) -> None:
    rec = message.record
    payload = {
        "ts": rec["time"].isoformat(),
        "level": rec["level"].name,
        "logger": rec["name"],
        "msg": rec["message"],
        "module": rec["module"],
        "line": rec["line"],
    }
    if rec["exception"] is not None:
        payload["exc"] = str(rec["exception"])
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def configure_logging(
    level: str = "INFO",
    log_dir: str | Path = "data/logs",
    json_console: bool = False,
    rotation: str = "100 MB",
    retention: str = "30 days",
) -> None:
    """Configure loguru sinks. Idempotent."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()

    if json_console:
        logger.add(_json_sink, level=level, filter=_redaction_filter, enqueue=True)
    else:
        logger.add(
            sys.stderr,
            level=level,
            filter=_redaction_filter,
            enqueue=True,
            backtrace=True,
            diagnose=False,  # diagnose=True prints locals — risk for secrets
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}:{line}</cyan> | <level>{message}</level>"
            ),
        )

    logger.add(
        log_dir / "trend_hl.log",
        level=level,
        rotation=rotation,
        retention=retention,
        compression="gz",
        filter=_redaction_filter,
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
    logger.add(
        log_dir / "errors.log",
        level="ERROR",
        rotation=rotation,
        retention=retention,
        compression="gz",
        filter=_redaction_filter,
        enqueue=True,
    )
    logger.info(f"Logging configured | level={level} dir={log_dir}")
