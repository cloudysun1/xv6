# syntax=docker/dockerfile:1.7
FROM python:3.11-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl tini git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- deps layer (cached) ----
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --upgrade pip && pip install -e ".[backtest]"

# ---- runtime ----
COPY scripts/ ./scripts/
COPY src/trend_hl/config/universe.yaml ./src/trend_hl/config/universe.yaml

RUN useradd -u 10001 -m trader && \
    mkdir -p /app/data /app/data/logs /app/data/bars && \
    chown -R trader:trader /app
USER trader

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python /app/scripts/healthcheck.py || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "scripts/run_live.py"]
