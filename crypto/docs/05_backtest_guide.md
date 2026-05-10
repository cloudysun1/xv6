# 05 · 回测指南:从能跑到能判断

> 回测的价值不是给你一个漂亮收益率,而是帮助你发现策略假设是否脆弱。本文先解释当前实现能做什么,再教你如何读输出、如何做稳健性检查、如何避免过拟合。

## 1. 当前回测实现的边界

当前 CLI 在 `src/trend_hl/app.py` 中定义:

```text
trend-hl backtest --symbol BTC --interval 1m --days 7
```

支持参数:

| 参数 | 默认值 | 当前含义 |
|---|---|---|
| `--symbol` | `BTC` | 单个标的,例如 BTC、ETH、SOL |
| `--interval` | `1m` | K 线周期,传给 Hyperliquid candleSnapshot |
| `--days` | `7` | 从当前 UTC 时间向前取多少天 |

当前不支持的参数:

| 参数 | 状态 | 替代做法 |
|---|---|---|
| `--initial-equity` | CLI 未实现 | 代码里 `Backtester(... starting_equity=Decimal("10000"))` 固定为 10000 |
| `--start-offset-days` | CLI 未实现 | 需要扩展 `_run_backtest()` 或写研究脚本 |
| 多标的一次回测 | CLI 未实现 | 当前 CLI 构造单标的 Universe |
| 自动保存报告文件 | CLI 未实现 | 当前只打印到控制台 |

这些边界很重要。不要把文档里的研究建议误读成当前 CLI 已经全部内置。研究流程可以比 CLI 更丰富,但执行前要确认代码是否支持。

## 2. 回测数据从哪里来

当前回测使用 Hyperliquid REST `/info` endpoint 的 `candleSnapshot`:

1. `trend-hl backtest` 读取 `.env` 中的 `HL_API_URL`。
2. 根据 `--days` 计算 `start` 和 `end` 毫秒时间戳。
3. 调用 `HyperliquidRestFeed.fetch_bars()` 拉取 K 线。
4. 把 K 线转成 Polars DataFrame。
5. 用同一套 `TrendFollower` 跑 bar-by-bar 回测。

优点:

1. 和 live/paper 共用信号与风险代码,减少“回测一套、实盘一套”的偏差。
2. 不需要自己先下载历史数据。
3. 适合烟雾测试和小规模研究。

限制:

1. 只有 K 线,没有真实历史 L2 订单簿。
2. 回测订单簿是从 K 线合成的简化模型。
3. 当前 CLI 每次只回测一个标的。
4. 太短的窗口不能代表策略长期表现。

## 3. 第一次运行

```bash
source .venv/bin/activate
trend-hl backtest --symbol BTC --interval 1m --days 7
```

可能输出:

```text
Total Return: 1.23%
CAGR:         87.65%
Sharpe:       1.10
Sortino:      1.48
Max DD:       -2.34%
# Trades:     18
Avg Fee/Tr:   1.2345
```

字段来自 `backtest/reporter.py`:

| 字段 | 含义 | 新手解释 |
|---|---|---|
| Total Return | 这段回测总收益率 | 账户从开头到结尾涨跌多少 |
| CAGR | 年化收益率 | 把短期收益机械换算成年化,短样本会非常夸张 |
| Sharpe | 平均收益/波动,年化 | 越高越好,但短样本很不可靠 |
| Sortino | 只惩罚下行波动的 Sharpe 类指标 | 对趋势策略可辅助看下跌风险 |
| Max DD | 最大回撤 | 从历史高点到低点最大跌幅 |
| # Trades | 成交笔数 | 太少说明统计意义不足 |
| Avg Fee/Tr | 平均每笔手续费 | 成本是否吞噬策略收益的线索 |

## 4. 怎么判断一次回测有没有意义

先看回测是否“有效”,再看结果是否“好”。

有效性检查:

| 检查项 | 合格信号 | 失败说明 |
|---|---|---|
| K 线数量 | `days` 对应的 bar 大致完整 | REST 没拉到数据或 symbol/interval 错 |
| 交易笔数 | 至少有足够样本 | 0 笔可能是窗口太短、信号不足或 bug |
| 回撤曲线 | 有涨跌过程 | 全平线可能未交易 |
| 费用 | 不为异常巨大 | 成本模型或成交逻辑可能异常 |
| 指标范围 | 没有 NaN/inf | 数学计算或数据质量问题 |

结果判断:

| 指标 | 粗略健康区间 | 警惕 |
|---|---|---|
| Sharpe | 长样本 > 1 才值得继续看 | 7 天 Sharpe 没有决定性 |
| Max DD | 应与你能承受的真实亏损匹配 | 回测回撤小不代表 live 小 |
| Trades | 越多统计越稳定 | 少于几十笔不要下结论 |
| Avg Fee/Tr | 成本应明显低于平均交易收益 | 成本太高说明 edge 很薄 |
| Total Return | 只做辅助 | 短期收益最容易误导 |

## 5. 为什么短周期 CAGR 会吓人

CAGR 是年化指标。假设 7 天赚 2%,机械年化会变成:

```text
(1.02)^(365/7) - 1
```

这不代表你真的会一年赚这么多。短样本年化的作用只是统一量纲,不能作为上线依据。对 1m 策略,更应该看多窗口、多标的、多市场状态下的 Sharpe、回撤、交易次数和成本敏感性。

## 6. 当前回测撮合模型

`Backtester._book_from_bar()` 用每根 K 线的 close 价格合成一个简化订单簿:

1. spread 设为 close 的 0.5bp 左右。
2. bid = close - spread/2。
3. ask = close + spread/2。
4. 深度用成交量的 10% 和 1 取最大值。

这意味着:

1. 它不能还原真实历史盘口排队。
2. 它不能准确模拟 maker 是否真的成交。
3. 它适合比较策略逻辑,不适合精确估计实盘滑点。
4. Paper 运行仍然不可替代。

## 7. 推荐研究流程

### 7.1 烟雾测试

目的:确认代码、环境、REST 和基本策略链路可用。

```bash
trend-hl backtest --symbol BTC --interval 1m --days 3
trend-hl backtest --symbol ETH --interval 1m --days 3
trend-hl backtest --symbol SOL --interval 1m --days 3
```

通过标准:

1. 三个命令都能跑完。
2. 没有 `no bars fetched`。
3. 指标不是 NaN/inf。

### 7.2 基础样本

目的:看策略在最近市场中是否有基本行为。

```bash
trend-hl backtest --symbol BTC --interval 1m --days 30
trend-hl backtest --symbol ETH --interval 1m --days 30
```

通过标准不是“必须赚钱”,而是:

1. 有足够交易次数。
2. 回撤没有超出你设定的风险承受。
3. 成本没有明显吞噬所有收益。
4. BTC 和 ETH 表现不完全依赖单一偶然窗口。

### 7.3 多窗口检查

当前 CLI 没有 `--start-offset-days`,所以不能直接指定历史偏移窗口。可行做法有两种:

1. 扩展 `_run_backtest(symbol, interval, days)` 增加 start/end 参数。
2. 写研究脚本直接调用 `HyperliquidRestFeed.fetch_bars()` 和 `Backtester`。

研究目标:

| 检查 | 理想情况 | 危险信号 |
|---|---|---|
| 不同月份 | 表现有波动但不全靠一个窗口 | 只有某一周赚钱 |
| 不同标的 | BTC/ETH/SOL 中有相近逻辑 | 只在冷门币单点爆发 |
| 不同参数 | 结果形成高原 | 只有一个参数点极好 |
| 不同成本 | Sharpe 缓慢下降 | 手续费或滑点稍高就崩 |

## 8. 参数稳健性怎么看

参数在 `src/trend_hl/config/strategy_params.py`。高风险参数包括:

| 参数 | 位置 | 增大会怎样 |
|---|---|---|
| `target_annual_vol` | `SizingParams` | 目标仓位变大,收益和回撤都放大 |
| `max_gross_leverage` | `SizingParams` 和 `.env` | 组合总敞口上限变大 |
| `kelly_fraction` | `SizingParams` | 在模型允许时更激进 |
| `min_signal_strength` | `SignalParams` | 增大后交易更少,减小后更容易交易噪声 |
| `snr_threshold` | `SignalParams` | 增大后 Kalman 信号更保守 |
| `chandelier_atr_mult` | `ExitParams` | 止损更宽,可能减少噪声止损但扩大亏损 |
| `rebalance_every_n_bars` | `ExecutionParams` | 增大后交易更慢、成本更低、反应更慢 |

稳健性原则:

1. 不要只找收益最高的参数。
2. 好参数附近应该也还可以,形成“高原”。
3. 如果某个参数点收益远高于周围点,大概率是过拟合。
4. 每次只改一类参数,否则不知道原因。
5. 先 paper 验证再 live。

## 9. 回测和 paper 怎么对齐

回测与 paper 的主要差异:

| 项 | 回测 | Paper |
|---|---|---|
| 行情 | 历史 K 线 | 实时 WebSocket 和 REST seed |
| 订单簿 | 合成 | 实时 L2 |
| 成交 | PaperAdapter + 合成 book | PaperAdapter + 实时 book |
| 延迟 | 基本没有 | 有网络和事件循环延迟 |
| 断线 | 没有 | 会发生 WebSocket 重连 |

你希望 paper 与回测在以下方面大致一致:

1. 交易频率没有数量级差异。
2. 信号方向和市场趋势肉眼上能解释。
3. 成本和成交数量没有异常膨胀。
4. 风控没有频繁 BLOCK。

如果差异很大,优先相信 paper 暴露的问题,因为它更接近实盘环境。

## 10. 常见错误解读

| 现象 | 可能原因 | 下一步 |
|---|---|---|
| `no bars fetched` | symbol 错、REST 不通、时间范围问题 | 换 BTC/ETH,检查 `HL_API_URL` |
| Trades 为 0 | 信号不足、窗口太短、参数太保守 | 拉长 `--days`,查信号逻辑 |
| Sharpe 极高 | 样本太短或偶然行情 | 多窗口、多标的复查 |
| Max DD 很小但收益高 | 交易太少或样本偏 | 看 trades 和权益曲线 |
| 手续费很高 | 换手过高 | 增大 rebalance 间隔或提高信号阈值 |
| 回测好 paper 差 | 真实盘口、延迟、重连、成交模型差异 | 延长 paper,看 orders/fills |

## 11. 不要做的事

- 不要用 7 天回测决定 live。
- 不要只看 Total Return。
- 不要在看到一个漂亮参数后继续调到更漂亮再上线。
- 不要忽略手续费、滑点和 funding。
- 不要把单标的表现推广到所有标的。
- 不要在没有 paper 7 天记录时上 live。
- 不要在代码不支持某个 CLI 参数时假设它已经生效。

## 12. 什么时候可以进入 paper

满足以下条件再进入 paper:

- [ ] 至少 BTC 和 ETH 的 30 天回测能正常跑完。
- [ ] 你理解输出每个指标。
- [ ] 你知道当前回测不是真实盘口模拟。
- [ ] 你没有只因为某个短期收益好看就做决定。
- [ ] 你已经读过 `docs/00_getting_started.md` 中的 `.env` 和标的池配置。
