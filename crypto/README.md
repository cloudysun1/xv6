# Trend-HL · Hyperliquid 趋势追踪量化交易系统

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]() [![License](https://img.shields.io/badge/license-MIT-green)]()

工业级、模块化、异步事件驱动的 **加密货币趋势追踪** 量化交易系统,原生对接 [Hyperliquid](https://hyperliquid.xyz) L1 永续合约 DEX。

> ⚠️ **风险提示**:加密货币交易存在高风险。本系统仅供学习与研究,作者不对实盘损失负任何责任。**首次部署前务必在 testnet 与 paper 模式下运行至少 7 天。**

---

## 核心特性

| 类别 | 详情 |
|---|---|
| **信号** | Kalman 滤波趋势 + 多周期 EWMA 动量 + Yang-Zhang 波动率 + ADX/Hurst 市态分类(详见 [docs/01_theory.md](docs/01_theory.md)) |
| **风控** | 5 层硬护栏(Kill-switch / 日亏损 / 单标的 DD / 时钟漂移 / 黑天鹅冷却) + Chandelier + Parabolic SAR + 时间止损 |
| **仓位** | 波动率目标 × 分数 Kelly × ERC 风险平价 |
| **执行** | Maker-first(Post-Only / ALO),`maker_timeout_s` 后回退 IOC;按订单簿深度切片,`reduce_only` 自动识别 |
| **数据** | WS `candle / l2Book / trades` + REST `candleSnapshot` 历史回填 + Parquet 持久化 |
| **架构** | Hexagonal Ports & Adapters,策略与 `IExchange` 接口解耦,回测 / paper / live 共用同一份策略代码 |
| **可观测性** | Loguru(行级 + JSON + 文件 rotate)+ Telegram/Discord webhook + 心跳 metrics + SQLite 审计 |
| **稳定性** | 全 asyncio + uvloop,WS 自动重连 + resync,token-bucket rate limiter,tenacity 指数退避,fail-closed 风控 |

## 目录结构

```
crypto/
├── src/trend_hl/        # 主包
│   ├── core/            # types / clock / event_bus
│   ├── config/          # pydantic settings + universe.yaml
│   ├── data/            # WS feed / REST feed / aggregator / store
│   ├── signals/         # Kalman / momentum / volatility / regime / engine
│   ├── risk/            # sizing / erc / exits / gates / risk_manager
│   ├── exchange/        # HL adapter / paper adapter / precision / rate-limiter
│   ├── execution/       # order_router / executor
│   ├── strategy/        # trend_follower
│   ├── monitor/         # notifier / heartbeat / metrics
│   ├── persistence/     # SQLite db
│   ├── backtest/        # engine / slippage / reporter
│   ├── utils/           # logging / retry / math_ops
│   └── app.py           # 装配 + Typer CLI
├── scripts/             # run_live.py / run_paper.py / run_backtest.py / healthcheck.py
├── docker/              # Dockerfile + docker-compose.yml
├── docs/                # 理论 / 架构 / 部署 / 运维
├── tests/               # 单元 + 集成测试
└── pyproject.toml
```

## 快速开始

### 1. 创建 Hyperliquid Agent Wallet(必须)

> **永远不要**把主钱包私钥放进 `.env`。Agent Wallet 仅有交易权限,无法转账或提现。

1. 访问 https://app.hyperliquid.xyz 连接主钱包
2. 进入 *Settings → API* 生成 Agent
3. 把生成的 **私钥**(0x…64 字节十六进制)写入 `.env` 的 `HL_API_SECRET`
4. 把 **主钱包地址** 写入 `HL_ACCOUNT_ADDRESS`

### 2. 安装与本地运行

```powershell
# Windows / PowerShell
git clone <this-repo>; cd crypto
copy .env.example .env       # 编辑 .env 填入凭据
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -U pip
pip install -e ".[dev,backtest]"
pytest -q

# 模拟盘
python -m trend_hl.app paper

# 回测最近 7 天 BTC
python -m trend_hl.app backtest --symbol BTC --interval 1m --days 7

# 实盘(谨慎)
python -m trend_hl.app live
```

```bash
# Linux / macOS
git clone <this-repo> && cd crypto
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,backtest]"
pytest -q
trend-hl paper
trend-hl backtest --symbol BTC --days 7
trend-hl live
```

### 3. Docker / VPS 一键部署

完整 step-by-step 见 [docs/03_deployment.md](docs/03_deployment.md)。简版:

```bash
cd docker
docker compose up -d --build
docker compose logs -f trend-hl
```

## 配置

* `.env` — 凭据 + 全局风险上限
* `src/trend_hl/config/universe.yaml` — 标的池
* `src/trend_hl/config/strategy_params.py` — 全部策略超参(`pydantic` schema,可在此调整 Kalman/动量/Kelly 等)

## 文档

* [00 从零开始使用手册](docs/00_getting_started.md)
* [01 量化理论教材](docs/01_theory.md)
* [02 系统架构](docs/02_architecture.md)
* [03 部署教程](docs/03_deployment.md)
* [04 运维 Runbook](docs/04_runbook.md)
* [05 回测指南](docs/05_backtest_guide.md)
* [99 文档迭代审计](docs/99_documentation_audit.md)

## License

MIT
