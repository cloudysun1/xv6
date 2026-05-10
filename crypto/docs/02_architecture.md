# 02 · 系统架构:模块、数据流与故障边界

> 架构文档的目标是让你知道“每个模块负责什么、不负责什么,数据从哪里来、到哪里去,出了问题应该怀疑哪一层”。如果你只想先使用系统,先读 `docs/00_getting_started.md`;如果要改代码或排障,再读本文。

## 1. 总体设计思想

Trend-HL 按“行情输入、信号计算、风险约束、订单执行、审计监控”拆成多层。每一层只做自己的事,避免策略代码直接伸手操作交易所。

核心原则:

| 原则 | 含义 | 代码体现 |
|---|---|---|
| Ports & Adapters | 策略依赖抽象接口,不依赖具体交易所实现 | `exchange/interfaces.py`, `HyperliquidAdapter`, `PaperAdapter` |
| 同一策略多模式复用 | backtest、paper、live 尽量共用 `TrendFollower` | `app.py` 中三种 CLI 入口都装配同一策略链 |
| 事件驱动 | WebSocket 行情先进入 `EventBus`,消费者异步处理 | `core/event_bus.py`, `data/hl_ws_feed.py` |
| 风控 fail-closed | 不健康时阻止新单或 KILL | `risk/gates.py` |
| Decimal 边界 | 交易所价格和数量用 `Decimal`,信号数学用 float/numpy | `core/types.py`, `exchange/precision.py`, `signals/` |
| 可审计 | 订单、成交、权益、信号写入 SQLite | `persistence/db.py` |

## 2. 目录和职责

| 目录 | 职责 | 典型文件 |
|---|---|---|
| `core/` | 全局类型、枚举、时钟、事件总线 | `types.py`, `enums.py`, `clock.py`, `event_bus.py` |
| `config/` | `.env` settings、标的池、策略参数 | `settings.py`, `strategy_params.py`, `universe.yaml` |
| `data/` | REST 历史数据、WebSocket 实时数据、bar 聚合与存储 | `hl_rest_feed.py`, `hl_ws_feed.py`, `bar_aggregator.py`, `store.py` |
| `signals/` | Kalman、动量、波动率、市态和信号合成 | `signal_engine.py`, `kalman_trend.py`, `momentum_bands.py` |
| `risk/` | 风控门、仓位 sizing、退出逻辑 | `gates.py`, `risk_manager.py`, `sizing.py`, `exits.py` |
| `strategy/` | 把 signal 和 risk 串成目标仓位 | `trend_follower.py` |
| `exchange/` | 交易所适配器、paper 适配器、精度和限流 | `hyperliquid_adapter.py`, `paper_adapter.py`, `precision.py` |
| `execution/` | 把目标仓位转成订单,执行 maker 和 IOC fallback | `executor.py`, `order_router.py` |
| `persistence/` | SQLite 审计库 | `db.py` |
| `monitor/` | 心跳指标和通知 | `heartbeat.py`, `notifier.py` |
| `backtest/` | 回测引擎和指标报告 | `engine.py`, `reporter.py` |
| `utils/` | 日志、重试、数学工具 | `logging.py`, `retry.py`, `math_ops.py` |

## 3. 运行模式如何装配

`src/trend_hl/app.py` 暴露三个 Typer 命令:

| 命令 | 入口函数 | 核心差异 |
|---|---|---|
| `trend-hl live` | `live()` | 使用 `HyperliquidAdapter`,会真实下单 |
| `trend-hl paper` | `paper()` | 使用 `PaperAdapter`,真实行情模拟成交 |
| `trend-hl backtest` | `backtest()` | 拉历史 K 线,用 `Backtester` bar-by-bar 回放 |

live 和 paper 共用 `_live_or_paper(mode)`。它负责:

1. 读取 `.env` 和默认策略参数。
2. 配置日志目录。
3. 加载 `universe.yaml` 中启用的标的。
4. 创建交易所适配器。
5. 通过 REST 拉交易所 meta。
6. 用 REST seed 最近历史 K 线。
7. 启动 WebSocket 订阅 candle 和 L2 book。
8. 创建 `TrendFollower` 和 `Executor`。
9. 连接 `data/orders.sqlite`。
10. 启动时钟、bar flusher、heartbeat 等后台任务。

## 4. 启动顺序

启动顺序可以理解为一条流水线:

```text
CLI command
     -> load_settings()
     -> configure_logging()
     -> load_universe()
     -> create exchange adapter
     -> fetch meta
     -> seed historical bars
     -> start WebSocket
     -> warmup strategy
     -> connect SQLite
     -> start background tasks
     -> consume events until stopped
```

每一步失败的影响不同:

| 阶段 | 失败影响 | 常见根因 |
|---|---|---|
| settings | 程序直接退出 | `.env` 缺失或字段格式错 |
| logging | 程序可能退出或无日志 | data 目录权限问题 |
| exchange connect | live 无法启动 | 私钥错、SDK/API 异常 |
| fetch meta | 可能继续,但精度信息缺失 | REST 网络问题 |
| seed history | 策略 warm-up 不充分 | REST 拉 K 线失败 |
| WebSocket | 行情不更新,风控 BLOCK | 网络或 WS 服务异常 |
| SQLite | 审计缺失 | 文件权限、锁、磁盘满 |

## 5. live/paper 实时数据流

```text
Hyperliquid WS candle/l2Book
     -> HyperliquidWsFeed._dispatch()
     -> EventBus.publish("bar" or "book")
     -> book_consumer updates latest_books
     -> bar_consumer upserts BarBufferRegistry
     -> BarStore buffers parquet writes
     -> every N primary bars calls _rebalance()
     -> adapter.fetch_account()
     -> TrendFollower.step()
     -> SignalEngine.compute()
     -> RiskManager.compute_target()
     -> Executor.execute_targets()
     -> OrderRouter.make_orders()
     -> exchange.place_order()
     -> adapter.fetch_recent_fills()
     -> Database inserts equity/signals/fills
```

几个关键点:

1. 默认 `rebalance_every_n_bars=5`,即主标的每 5 根 K 线触发一次调仓。
2. 主标的是 `universe.active[0]`,默认 BTC。
3. `BarStore` 每 60 秒把 buffered bars 写到 `data/bars/<symbol>/<interval>/`。
4. SQLite 文件当前是 `data/orders.sqlite`。
5. 心跳默认每 300 秒发送一次。

## 6. 回测数据流

```text
trend-hl backtest
     -> load_settings()
     -> HyperliquidRestFeed.fetch_bars()
     -> Polars DataFrame
     -> Universe(symbol=[requested symbol])
     -> Backtester.run()
     -> synthetic L2 book from each bar
     -> TrendFollower.step()
     -> Executor + PaperAdapter
     -> compute_stats()
     -> print report_text()
```

回测与 live/paper 的相同点:

1. 使用同一套 `TrendFollower`。
2. 使用同一套 `RiskManager`、`SignalEngine` 和 `Executor`。
3. 目标仓位生成逻辑尽量一致。

差异:

1. 回测订单簿是由 K 线 close 合成的,不是历史真实盘口。
2. 回测当前 CLI 单次只跑一个标的。
3. 回测报告当前只打印,不自动写文件。
4. 回测没有真实网络断线、延迟、交易所拒单等问题。

## 7. 配置流

`Settings` 使用 `pydantic-settings` 从 `.env` 和系统环境变量读取。重要配置流向:

```text
.env
     -> Settings
     -> HyperliquidCreds for adapter/rest/ws
     -> NotificationConfig for notifier
     -> StrategyParams overrides for risk/sizing caps
```

当前 `.env` 会覆盖这些全局风险上限:

| `.env` 变量 | 覆盖到 |
|---|---|
| `EQUITY_FLOOR_USD` | `params.risk.equity_floor_usd` |
| `DAILY_LOSS_LIMIT_PCT` | `params.risk.daily_loss_limit_pct` |
| `MAX_GROSS_LEVERAGE` | `params.sizing.max_gross_leverage` |

其他策略参数目前主要在 `strategy_params.py` 中修改。也就是说,如果你想改 Kalman、动量、ATR、止损、rebalance 频率,当前实现不是通过 `.env` 覆盖,而是改代码里的 pydantic 默认值或增加新的配置层。

## 8. 信号和风险如何衔接

`TrendFollower.step()` 对每个启用标的执行:

1. 从 `BarBufferRegistry` 取最近 bars。
2. 如果 bars 少于 64,跳过该标的。
3. `SignalEngine.compute()` 生成方向、强度和 metadata。
4. 根据最近 1-bar return 更新黑天鹅 z-score。
5. 从最新 L2 book 计算 mid price。
6. `RiskManager.compute_target()` 用信号、权益、波动率、权重和风控上下文计算目标仓位。
7. 如果已有仓位,更新 trailing exit 状态。
8. 返回 signals 和 targets。

风控结果分三类:

| 结果 | 含义 | 目标仓位 |
|---|---|---|
| `ALLOW` | 可以交易 | 使用 sizing 计算结果 |
| `BLOCK` | 暂时阻止新动作 | 保持已有仓位 |
| `KILL` | 严重风险 | 目标设为 0 |

## 9. 执行层如何下单

执行层的输入是“目标数量”,不是“买入/卖出信号”。流程:

1. `compute_delta(target, current)` 算当前仓位与目标仓位的差。
2. 根据 delta 正负决定 BUY 或 SELL。
3. 用 `round_size()` 和 `round_price()` 满足 Hyperliquid 精度。
4. 根据前 5 档订单簿和 `slice_max_pct_of_book` 切片。
5. 生成 post-only ALO maker 限价单。
6. 如果 maker `ACCEPTED`,等待 `maker_timeout_s`。
7. 撤掉剩余 maker,用 IOC fallback 尝试成交。

这套设计的意图是:优先控制交易成本,但不让调仓无限等待。

## 10. 持久化和审计

SQLite schema 在 `persistence/db.py` 中。当前表:

| 表 | 主用途 | 写入时机 |
|---|---|---|
| `orders` | 订单请求和交易所响应 | 当前 schema 有 insert 方法,但实时路径主要统计 report;需要确认调用覆盖 |
| `fills` | 成交记录 | 每次 rebalance 后拉最近 fills |
| `equity_snapshots` | 权益和仓位快照 | 每次 rebalance 成功 fetch_account 后 |
| `signals_log` | 信号方向、强度、目标杠杆、metadata | 每次 rebalance 后 |

需要特别注意:当前 `_rebalance()` 没有直接调用 `db.insert_order()` 记录每个 OrderAck,主要写 equity、signals、fills。若你需要完整订单审计,应增强 `Executor` 或 `_rebalance()` 把订单 ack 写入数据库。

## 11. 后台任务

| 任务 | 创建位置 | 周期/触发 | 职责 |
|---|---|---|---|
| `CLOCK.run_forever` | `_live_or_paper()` | 约 30s | 监测时钟漂移 |
| `BarStore.run_flusher` | `_live_or_paper()` | 默认 60s | 写 parquet bar 文件 |
| `heartbeat_loop` | `_live_or_paper()` | 默认 300s | 日志和通知心跳 |
| WebSocket task | `HyperliquidWsFeed.start()` | 事件驱动 | 订阅行情、重连、resync |
| `book_consumer` | `_live_or_paper()` | event | 维护最新订单簿 |
| `bar_consumer` | `_live_or_paper()` | event | 维护 bars、触发 rebalance |
| `ctrl_consumer` | `_live_or_paper()` | event | 处理 resync |

## 12. 故障边界

| 故障 | 检测位置 | 自动行为 | 人工动作 |
|---|---|---|---|
| WS 超时 | `HyperliquidWsFeed.healthy` | 重连,风控 BLOCK | 看网络和 WS 日志 |
| 时钟漂移 | `CLOCK.state.drift_ms` | 风控 BLOCK | 修 chrony |
| 权益低于 floor | `RiskGates.evaluate_pretrade` | KILL | 停机、核对 Web UI |
| 当日亏损超限 | `RiskGates.evaluate_pretrade` | KILL | 停机、复盘 |
| 交易所下单异常 | `HyperliquidAdapter.place_order` | 返回 REJECTED | 查 raw_json、授权、保证金 |
| SQLite 锁 | `Database` 方法 | 写入失败可能被 suppress | 停服务 checkpoint |
| REST meta 失败 | 启动或回测 | 可能缺 meta | 重试、检查网络 |

## 13. 当前实现的已知边界

这些不是批评,而是帮助你正确预期系统能力:

1. 回测 CLI 当前只支持单标的、固定起始权益、向前 `days` 窗口。
2. 回测使用合成订单簿,不能精确模拟真实 maker 排队。
3. `.env` 只覆盖少量风险上限,大多数策略参数仍在代码默认值里。
4. `orders` 表 schema 存在,但当前实时路径没有完整插入每个 OrderAck 的调用。
5. fill 持久化依赖 rebalance 后拉最近成交,不是独立 user fills stream。
6. Docker 默认命令是 live,首次容器化时应主动改成 paper 或覆盖 command。

## 14. 修改代码时的原则

如果你要扩展系统,优先遵守这些边界:

1. 新交易所接入应实现 `IExchange`,不要改策略层去适配交易所细节。
2. 新风控应进入 `risk/gates.py` 或 `RiskManager`,不要散落在执行层。
3. 新信号应进入 `signals/`,由 `SignalEngine` 合成。
4. 新配置应先进入 typed pydantic model,再从 `.env` 或 YAML overlay。
5. 新持久化字段应先迁移 schema,再改写入路径。
6. live 行为变更必须先能在 paper 或 backtest 中复现基本逻辑。

