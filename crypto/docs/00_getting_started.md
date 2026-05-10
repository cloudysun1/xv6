# 00 · 从零开始使用手册

> 这份手册假设你对 Python、Linux、Hyperliquid、量化交易、永续合约、API 私钥、回测、paper trading 都可能不了解。它的目标不是炫技,而是让你能安全、可重复地把 Trend-HL 从“代码仓库”推进到“能回测、能模拟、能上线、能排障”的系统。

## 1. 先理解这套系统在做什么

Trend-HL 是一个 Hyperliquid 永续合约趋势追踪系统。它会持续接收行情,把价格整理成 K 线,计算趋势信号,用风险模型换算成目标仓位,再通过交易所接口把当前仓位调整到目标仓位。

用最朴素的话说:

1. 行情进来:WebSocket 收到 BTC、ETH、SOL 等标的的 K 线和订单簿。
2. 信号生成:系统判断“上涨趋势、下跌趋势、还是没有足够趋势”。
3. 风险过滤:系统检查余额、日亏损、网络、时钟、极端波动等条件。
4. 仓位计算:信号越强、波动越低、权重越高,目标仓位越大;反之越小或归零。
5. 订单执行:优先挂 maker 限价单,超时没成交再用 IOC 限价单吃流动性。
6. 记录审计:订单、成交、权益、信号和日志写入本地 `data/`。

这不是一个“稳赚脚本”。趋势策略的基本特征是:很多时候不交易或小亏,少数大趋势贡献主要收益。你应该先用回测理解策略,再用 paper 模式观察真实行情下的行为,最后才考虑小金额 live。

## 2. 三种运行模式怎么选

| 模式 | 命令 | 使用真实行情 | 使用真实资金 | 用途 |
|---|---|---:|---:|---|
| 回测 | `trend-hl backtest --symbol BTC --interval 1m --days 7` | 历史 REST K 线 | 否 | 研究最近一段历史上策略会怎样表现 |
| Paper | `trend-hl paper` | 是 | 否 | 用真实实时行情测试系统稳定性和交易逻辑 |
| Live | `trend-hl live` | 是 | 是 | 实盘交易,必须在前两步通过后再用 |

选择顺序应当固定为:先 backtest,再 paper,最后 live。不要跳过 paper,因为回测只看历史 K 线,无法暴露 WebSocket 中断、订单簿缺失、凭据错误、服务器时钟漂移等实盘问题。

## 3. 你需要知道的基础词汇

| 词 | 含义 | 在本系统中的体现 |
|---|---|---|
| 标的 / symbol | 要交易的合约,如 BTC、ETH、SOL | 写在 `src/trend_hl/config/universe.yaml` |
| K 线 / bar | 一段时间内的开高低收和成交量 | 默认使用 `1m` K 线 |
| 订单簿 / L2 book | 当前买卖盘深度 | 用于决定挂单价格和切片大小 |
| 信号 / signal | 策略对方向和强度的判断 | 写入 SQLite 的 `signals_log` 表 |
| 目标仓位 / target position | 系统希望最终持有的数量 | `TrendFollower` 输出给 `Executor` |
| maker | 挂单等待别人来成交 | 默认优先使用,成本通常更低 |
| IOC | 立即成交或取消的限价单 | maker 超时后作为 fallback |
| reduce-only | 只能减仓,不能反向开仓 | 平仓或缩仓时使用 |
| kill-switch | 风险硬停止 | 日亏损、权益过低时触发 |
| paper trading | 模拟成交 | 用真实行情,但不会向交易所下真实订单 |

## 4. 仓库里哪些文件最重要

| 路径 | 作用 | 什么时候你会改 |
|---|---|---|
| `.env` | 私钥、主钱包地址、API URL、日志目录、风险上限 | 部署和切换主网/测试网时 |
| `.env.example` | `.env` 模板 | 不放真实密钥 |
| `src/trend_hl/config/universe.yaml` | 允许交易的标的和权重 | 增删 BTC/ETH/SOL 等标的时 |
| `src/trend_hl/config/strategy_params.py` | 策略、风控、执行默认参数 | 做研究或调参时 |
| `src/trend_hl/app.py` | CLI 入口和系统装配 | 通常不需要改 |
| `data/logs/trend_hl.log` | 常规日志 | 排障时第一时间看 |
| `data/logs/errors.log` | 错误日志 | 看到异常或停止交易时看 |
| `data/orders.sqlite` | SQLite 审计库,当前主要写权益、信号和成交 | 查询运行结果时看 |
| `data/bars/` | 实时 K 线 parquet 文件 | 复盘或本地分析时看 |

注意:当前实现的 SQLite 文件名是 `data/orders.sqlite`,不是 `data/trend_hl.sqlite`。

## 5. 安装前准备

你至少需要:

| 项目 | 最低要求 | 为什么需要 |
|---|---|---|
| Python | 3.11 或 3.12 | `pyproject.toml` 要求 `>=3.11,<3.13` |
| 网络 | 能访问 `api.hyperliquid.xyz` | 拉历史数据、订阅行情、提交订单 |
| Hyperliquid 主钱包地址 | `0x` 开头、42 个字符 | 系统查询和交易这个账户的仓位 |
| Hyperliquid Agent 私钥 | `0x` 开头、66 个字符 | 只用于签交易指令,不是主钱包私钥 |
| USDC 保证金 | paper 不需要,live 需要 | live 模式真实交易会占用保证金 |

Agent Wallet 很重要:它是专门给程序交易用的授权钱包。你绝不应该把主钱包私钥写进 `.env`。主钱包私钥一旦泄露,资金可能被转走;Agent 私钥泄露也很危险,但它通常只能交易,不能提现。

## 6. 第一次本地安装

Linux 或 macOS:

```bash
git clone <YOUR-REPO-URL> crypto
cd crypto
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e ".[dev,backtest]"
pytest -q
```

Windows PowerShell:

```powershell
git clone <YOUR-REPO-URL> crypto
cd crypto
copy .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip wheel
pip install -e ".[dev,backtest]"
pytest -q
```

成功标志:

1. `pip install` 没有报红色 traceback。
2. `pytest -q` 结束时没有 failed。
3. 运行 `trend-hl --help` 能看到 `live`、`paper`、`backtest` 命令。

如果 `trend-hl` 命令找不到,通常是虚拟环境没有激活。Linux/macOS 重新执行 `source .venv/bin/activate`;Windows 重新执行 `.venv\Scripts\Activate.ps1`。

## 7. 配置 `.env`

`.env` 是系统启动时读取的环境变量文件。它不应该提交到 git,权限也应该尽量收紧。

最小可用配置:

```dotenv
HL_ACCOUNT_ADDRESS=0x你的主钱包地址
HL_API_SECRET=0x你的Agent私钥
HL_API_URL=https://api.hyperliquid.xyz
HL_WS_URL=wss://api.hyperliquid.xyz/ws
HL_NETWORK=mainnet

TREND_HL_ENV=paper
TREND_HL_LOG_LEVEL=INFO
TREND_HL_DATA_DIR=./data

EQUITY_FLOOR_USD=200
DAILY_LOSS_LIMIT_PCT=3.0
MAX_GROSS_LEVERAGE=3.0
```

字段解释:

| 字段 | 必填 | 解释 | 常见错误 |
|---|---:|---|---|
| `HL_ACCOUNT_ADDRESS` | 是 | 持有资金的主钱包地址 | 填成 Agent 地址会导致查不到真实仓位 |
| `HL_API_SECRET` | 是 | Agent Wallet 私钥 | 填主钱包私钥是严重安全事故 |
| `HL_API_URL` | 是 | REST API 地址 | 主网和测试网不能混用 |
| `HL_WS_URL` | 是 | WebSocket 地址 | 主网和测试网不能混用 |
| `HL_NETWORK` | 否 | 说明网络环境 | 当前代码主要用 URL 决定实际连接 |
| `TREND_HL_ENV` | 否 | 运行意图标记 | CLI 命令才真正决定 live/paper/backtest |
| `TREND_HL_LOG_LEVEL` | 否 | 日志等级 | 排障时可临时设为 `DEBUG` |
| `TREND_HL_DATA_DIR` | 否 | 数据目录 | 默认 `./data` |
| `EQUITY_FLOOR_USD` | 否 | 权益低于该值触发 KILL | 不要设高于账户权益 |
| `DAILY_LOSS_LIMIT_PCT` | 否 | 当日亏损百分比上限 | 例如 `3.0` 表示 -3% |
| `MAX_GROSS_LEVERAGE` | 否 | 组合总名义杠杆上限 | 新手建议先低于默认值 |

主网地址:

```dotenv
HL_API_URL=https://api.hyperliquid.xyz
HL_WS_URL=wss://api.hyperliquid.xyz/ws
```

测试网地址:

```dotenv
HL_API_URL=https://api.hyperliquid-testnet.xyz
HL_WS_URL=wss://api.hyperliquid-testnet.xyz/ws
HL_NETWORK=testnet
```

## 8. 配置交易标的

标的池在 `src/trend_hl/config/universe.yaml`。默认启用 BTC、ETH、SOL,禁用 ARB、AVAX。

```yaml
symbols:
  - symbol: BTC
    enabled: true
    weight: 1.0
  - symbol: ETH
    enabled: true
    weight: 1.0
  - symbol: SOL
    enabled: true
    weight: 0.7
```

字段解释:

| 字段 | 解释 |
|---|---|
| `symbol` | Hyperliquid 上的合约名称,必须和交易所 `meta` 返回一致 |
| `enabled` | `true` 表示允许交易,`false` 表示忽略 |
| `weight` | 仓位权重,同样信号下权重越高目标仓位越大 |

新手建议不要一开始启用太多小币种。流动性越差,滑点、拒单、极端波动和风控触发越难理解。

## 9. 第一次回测

运行最近 7 天 BTC 回测:

```bash
trend-hl backtest --symbol BTC --interval 1m --days 7
```

你应该看到类似输出:

```text
Total Return: 0.00%
CAGR:         0.00%
Sharpe:       0.00
Sortino:      0.00
Max DD:       0.00%
# Trades:     0
Avg Fee/Tr:   0.0000
```

这些数字只是示例,不是目标收益。第一次回测的重点是确认:

1. 系统能访问 Hyperliquid REST。
2. 能拉到历史 K 线。
3. 策略能完整跑完。
4. 输出指标不是程序异常。

如果日志说 `no bars fetched`,先检查 `HL_API_URL` 是否能访问,标的名是否正确,以及本机时间是否离谱。

## 10. 第一次 paper 运行

Paper 模式会连接真实行情,但订单在内存中的 `PaperAdapter` 模拟成交,不会使用真实资金。

```bash
trend-hl paper
```

至少观察 10 分钟。你希望看到:

1. `trend-hl starting in paper mode`
2. `Loaded meta for ... HL perps`
3. `WS connected`
4. 周期性 `[heartbeat] equity=... bars=... sigs=... orders=... fills=...`
5. `data/logs/trend_hl.log` 持续更新

你不一定会立刻看到订单。趋势策略可能因为 warm-up、震荡市、信号不足、订单簿未就绪而保持空仓。没有订单不等于失败;有 `ERROR`、`KILL`、`ws_unhealthy`、`clock_drift` 才需要排障。

停止 paper:

```text
Ctrl-C
```

停止后检查数据:

```bash
sqlite3 data/orders.sqlite 'SELECT symbol,direction,strength,target_leverage FROM signals_log ORDER BY ts_ms DESC LIMIT 10;'
sqlite3 data/orders.sqlite 'SELECT equity,margin_used,free_margin FROM equity_snapshots ORDER BY ts_ms DESC LIMIT 10;'
ls data/bars
```

## 11. 上 live 前的最低验收清单

不要因为一次回测好看就 live。最低验收标准:

- [ ] `pytest -q` 通过。
- [ ] 回测至少覆盖 30 天,并且不是只看一个标的。
- [ ] Paper 连续运行至少 7 天,没有长期 WebSocket 中断。
- [ ] 你知道 `data/orders.sqlite` 里每张表的含义。
- [ ] 你知道怎么停止服务、怎么手动平仓、怎么撤销 Agent。
- [ ] `EQUITY_FLOOR_USD` 低于账户权益,但高到能阻止灾难性亏损。
- [ ] `DAILY_LOSS_LIMIT_PCT` 是你能接受的真实日亏损。
- [ ] VPS 时间同步正常,`chronyc tracking` 没有明显漂移。
- [ ] 已经在 Hyperliquid Web UI 熟悉手动平仓流程。

## 12. 第一次 live 运行

确认你确实准备好后,先用小资金、低风险参数运行:

```bash
trend-hl live
```

你需要同时开着两个窗口:

1. 终端日志:观察 `trend-hl live` 输出或 `journalctl -fu trend-hl`。
2. Hyperliquid Web UI:观察真实订单、持仓、保证金和 PnL。

第一次 live 的目标不是赚钱,而是验证全链路:

1. Agent 可以签名下单。
2. 订单精度没有被拒。
3. 本地 SQLite 能记录成交和权益。
4. Web UI 持仓和本地查询能对上。
5. 停止服务后没有孤儿订单。

## 13. 数据和日志怎么看

常用日志命令:

```bash
tail -f data/logs/trend_hl.log
tail -f data/logs/errors.log
grep -i 'KILL\|ERROR\|REJECTED\|heartbeat' data/logs/trend_hl.log | tail -50
```

常用 SQLite 查询:

```bash
sqlite3 data/orders.sqlite '.tables'
sqlite3 data/orders.sqlite 'SELECT * FROM equity_snapshots ORDER BY ts_ms DESC LIMIT 5;'
sqlite3 data/orders.sqlite 'SELECT symbol,side,size,price,status,raw_json FROM orders ORDER BY ts_ms DESC LIMIT 20;'
sqlite3 data/orders.sqlite 'SELECT symbol,side,price,size,fee FROM fills ORDER BY ts_ms DESC LIMIT 20;'
sqlite3 data/orders.sqlite 'SELECT symbol,direction,strength,target_leverage,metadata_json FROM signals_log ORDER BY ts_ms DESC LIMIT 20;'
```

表的含义:

| 表 | 含义 |
|---|---|
| `orders` | 订单审计表。当前 schema 和写入方法已存在,但实时主循环不保证每个 OrderAck 都写入,为空时请结合日志和 Web UI 判断 |
| `fills` | 最近成交记录,来自交易所或 paper 适配器 |
| `equity_snapshots` | 每次调仓时抓取的账户权益和仓位快照 |
| `signals_log` | 每个标的每次调仓周期生成的信号 |

## 14. 常见第一次卡住点

| 现象 | 最可能原因 | 先做什么 |
|---|---|---|
| `invalid EVM address` | `HL_ACCOUNT_ADDRESS` 格式错 | 确认是主钱包地址,`0x` 加 40 位十六进制 |
| `invalid private key length` | `HL_API_SECRET` 格式错 | 确认是 Agent 私钥,`0x` 加 64 位十六进制 |
| `no bars fetched` | REST 地址、网络或 symbol 错 | `curl https://api.hyperliquid.xyz/info` |
| paper 没订单 | warm-up 或信号不足 | 看 `signals_log`,不要急着 live |
| `ws_unhealthy` | WebSocket 没收到消息 | 检查网络、防火墙、服务商 |
| `clock_drift` | 服务器时间不同步 | Linux 上重启 chrony |
| `REJECTED` | 精度、保证金、最小名义金额或授权问题 | 查 `orders.raw_json` 和 Hyperliquid Web UI |

## 15. 文档阅读顺序

建议按这个顺序读:

1. `docs/00_getting_started.md`:先跑起来,知道每个文件和命令做什么。
2. `docs/05_backtest_guide.md`:学会判断回测输出,避免把过拟合当成收益。
3. `docs/03_deployment.md`:把系统放到 VPS 或 Docker 上 7x24 跑。
4. `docs/04_runbook.md`:出问题时按症状排障。
5. `docs/02_architecture.md`:理解代码模块和数据流。
6. `docs/01_theory.md`:理解策略背后的数学和风险假设。
