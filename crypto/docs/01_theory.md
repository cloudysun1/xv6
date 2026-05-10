# 01 · 量化理论教材

> 本教材解释 Trend-HL 背后的趋势追踪、信号、波动率、仓位和风险控制。它假设你可能第一次接触量化交易,所以先讲概念,再讲公式,最后讲公式如何落到当前代码。公式不是为了显得复杂,而是为了让每个参数的含义可追踪、可讨论、可调试。

---

## 0. 阅读路线与基础概念

如果你完全不懂量化,先抓住一句话:本系统不是预测“下一分钟一定涨还是跌”,而是在价格已经表现出趋势时,用受控仓位跟随趋势,并在趋势消失或风险过大时退出。

### 0.1 从价格到订单的完整链条

```text
价格/K线
	-> 计算收益率和波动率
	-> 判断趋势方向和强度
	-> 判断市场是否适合趋势策略
	-> 把信号换算成目标仓位
	-> 检查风控硬条件
	-> 生成订单
	-> 记录成交、权益和信号
```

每一层都可能让最终仓位变小或归零。例如趋势信号很强,但波动率太高、当日亏损超限、WebSocket 不健康,系统仍然应该少交易或不交易。

### 0.2 最小术语表

| 术语 | 直观含义 | 数学/系统含义 |
|---|---|---|
| 价格 `P_t` | 某一时刻的成交或收盘价 | K 线 close 常用作观察值 |
| 对数价格 `p_t` | 把价格取 log | `p_t = ln(P_t)`,便于把涨跌看作加法 |
| 收益率 `r_t` | 一段时间涨跌幅 | 简单收益 `P_t/P_{t-1}-1` 或对数收益 `p_t-p_{t-1}` |
| 波动率 `sigma` | 价格抖动幅度 | 仓位大小和止损宽度的核心输入 |
| 信号 `s_t` | 方向和强度 | 通常压缩在 `[-1,1]` |
| 多头 | 看涨仓位 | size > 0 |
| 空头 | 看跌仓位 | size < 0 |
| 名义仓位 notional | 仓位美元价值 | `abs(size) * price` |
| 杠杆 | 名义仓位 / 权益 | 2x 表示仓位价值约为账户权益两倍 |
| 回撤 | 从历史高点跌了多少 | 衡量痛苦和爆仓风险 |
| 滑点 | 预期价格和实际成交价格差 | 流动性越差、订单越大越严重 |

### 0.3 为什么用对数价格

价格从 100 到 110 是 +10%,从 1000 到 1010 只是 +1%。直接看价格差会把高价资产的变化放大。对数收益近似百分比收益:

$$
r_t^{log}=\ln(P_t)-\ln(P_{t-1})\approx \frac{P_t-P_{t-1}}{P_{t-1}}
$$

这让 BTC、ETH、SOL 的涨跌可以在同一个尺度上比较。

### 0.4 趋势追踪的基本假设

趋势追踪依赖几个经验事实,不是数学定理:

1. 市场有时会出现持续方向性移动。
2. 趋势早期很难确认,确认时往往已经走了一段。
3. 多数突破会失败,所以胜率不一定高。
4. 少数大趋势需要覆盖许多小亏损。
5. 仓位控制比单次方向判断更重要。

因此,衡量趋势系统不能只看胜率。一个胜率 45% 的策略,如果平均盈利远大于平均亏损,仍然可能有正期望。

### 0.5 加密永续合约的特殊风险

Hyperliquid 上交易的是永续合约,不是现货。你必须理解:

| 风险 | 解释 | 系统如何应对 |
|---|---|---|
| 杠杆风险 | 仓位价值可能大于账户权益 | `max_leverage_per_symbol`, `max_gross_leverage` |
| 强平风险 | 保证金不足会被交易所强平 | 权益 floor、波动率目标、止损 |
| funding | 多空之间定期支付资金费 | 研究时必须纳入成本意识 |
| 24x7 | 没有传统收盘休息 | 需要 heartbeat、runbook、自动重连 |
| 跳变和插针 | 极端波动可能瞬间出现 | black-swan gate、cooldown、止损 |

---

## 1. 趋势的统计学定义

设标的对数价格 $p_t = \ln P_t$。我们假设其由"隐含趋势速度" $\nu_t$ 与高斯噪声叠加产生。这一假设并非真实(尤其重尾、跳跃),但它是 **首阶段近似**,后续层会处理非高斯特性。

### 1.1 状态空间模型(局部线性趋势)

$$
\begin{aligned}
\mu_t &= \mu_{t-1} + \nu_{t-1}\Delta t + w_t^\mu, & w_t^\mu &\sim\mathcal N(0, Q_\mu) \\
\nu_t &= \nu_{t-1} + w_t^\nu, & w_t^\nu &\sim\mathcal N(0, Q_\nu) \\
p_t &= \mu_t + \varepsilon_t, & \varepsilon_t &\sim\mathcal N(0, R)
\end{aligned}
$$

矩阵形式 $x_t = (\mu_t,\nu_t)^\top$:

$$ x_t = F x_{t-1} + w_t,\quad F=\begin{pmatrix}1&\Delta t\\0&1\end{pmatrix},\quad y_t = H x_t + \varepsilon_t,\quad H=(1,0) $$

### 1.2 Kalman 递推(实现见 `signals/kalman_trend.py`)

* **预测**: $\hat x_{t|t-1} = F\hat x_{t-1|t-1}$, $P_{t|t-1} = FP_{t-1|t-1}F^\top + Q$
* **更新**: 残差 $y = p_t - H\hat x_{t|t-1}$, $S = HPH^\top + R$, $K = PH^\top S^{-1}$, $\hat x_{t|t} = \hat x_{t|t-1} + Ky$, $P_{t|t} = (I-KH)P_{t|t-1}$

输出 $(\hat\mu_{t|t}, \hat\nu_{t|t}, \sigma_\nu)$。**关键工程点**:超参 $Q,R$ 控制平滑度。直观对应:
* 增大 $Q_\nu$ → 趋势速度可以快速变化(适合快趋势市场)
* 增大 $R$ → 滤波器更"信任"模型,产生更平滑的曲线
* 实务推荐先用 EM 在历史数据上拟合,再固定。

### 1.3 信噪比(SNR)信号化

$$ \mathrm{SNR}_t = \frac{\hat\nu_{t|t}}{\sigma_\nu(t)},\quad s^{\text{kal}}_t = \tanh\!\left(\frac{\mathrm{SNR}_t}{\theta}\right)\in(-1,1) $$

`tanh` 起到饱和作用,让极端 SNR 不主导组合;阈值 $\theta\in[1.5,2.5]$ 控制开仓激进程度。

---

## 2. 多周期动量融合(Cross-Sectional / Time-Series)

### 2.1 单周期 EWMA 动量

衰减常数 $\lambda$,半衰期 $\tau = \ln 2/\lambda$。EWMA 形式:

$$ M_t^{(\lambda)} = (1-\alpha)M_{t-1}^{(\lambda)} + \alpha r_t,\quad \alpha = 1 - e^{-\lambda \Delta t} $$

其归一化版本除以 EWMA 标准差 $\sigma^{(\lambda)}$:

$$ z_t^{(\lambda)} = M_t^{(\lambda)}/\sigma^{(\lambda)}_t $$

### 2.2 多周期叠加

我们采用 3 个半衰期:**16 / 64 / 256 bars**(对应 ~16min / 1h / 4h 的有效记忆,1m K 线下),权重 0.4 / 0.4 / 0.2。融合信号:

$$ s^{\text{mom}}_t = \sum_i w_i \cdot \tanh\left(\frac{M_t^{(\lambda_i)}}{k\,\sigma^{(\lambda_i)}_t}\right) $$

理论依据:Baz et al. (2015, *Dissecting Investment Strategies*) 显示多周期动量在 risk-adjusted 维度上优于任何单一周期,因为不同 regime 的最优衰减不同。

### 2.3 信号合成

最终 $s_t = 0.5 s^{\text{kal}}_t + 0.5 s^{\text{mom}}_t$,然后乘以三个 **门控**:
* `agree_gate`:Kalman 与 momentum 同号 → 1.0,否则 0.3
* `regime_gate`:ADX > 20 趋势市 → 1.0,否则 0.4
* `snr_gate`:|SNR| ≥ θ → 1.0,否则 0.5

如果 $|s_t|<$ `min_signal_strength`(0.15),仓位强制归零。

---

## 3. 波动率自适应:Yang-Zhang + ATR

### 3.1 为何不用收盘价标准差

加密 24×7 无开盘跳空,但仍存在极强日内 OHLC 离散。仅使用收盘价的 $\sigma$ 会低估真实风险约 30-50%。

### 3.2 Yang-Zhang(2000)估计量

$$ \sigma_{YZ}^2 = \sigma_O^2 + k\sigma_C^2 + (1-k)\sigma_{RS}^2 $$

* $\sigma_O^2$ — 隔夜回报方差
* $\sigma_C^2$ — 日内开盘到收盘方差
* $\sigma_{RS}^2$ — Rogers-Satchell 估计量,基于 OHLC,**对漂移无偏**
* $k = 0.34/(1.34 + (n+1)/(n-1))$ 由方差最小化导出

### 3.3 ATR 混合

ATR(Wilder)对极端突破响应更快,但漂移敏感。我们 **β 加权混合**:

$$ \sigma_t^{\text{adj}} = \beta\,\sigma_{YZ,t} + (1-\beta)\,\mathrm{ATR}_{14}(t)/P_t,\quad \beta\approx0.7 $$

得到 *相对波动率*(无量纲),用于仓位计算与止损宽度。

---

## 4. 仓位管理

### 4.1 波动率目标(Vol Targeting)

设组合年化目标波动 $\sigma^*$ (默认 30%)。单标的 notional:

$$ N_i = \mathrm{Equity}\cdot\frac{\sigma^*}{\sigma_i^{\text{ann}}}\cdot s_i\cdot w_i $$

其中 $\sigma_i^{\text{ann}} = \sigma_i^{\text{bar}}\sqrt{B}$,$B$ = 年内 bar 数(1m → 525,600)。该公式保证组合 *ex-ante* 波动等于 $\sigma^*$ × $\sum |s_i w_i|$,与杠杆解耦。

### 4.2 分数 Kelly 修正

完整 Kelly $f^* = \mu/\sigma^2$ 在重尾下 over-bets。我们用 **Quarter-Kelly**:

$$ f = \kappa \cdot \frac{\mu}{\sigma^2},\quad \kappa = 0.25 $$

$\mu$ 由滚动 Sharpe 与 $\sigma$ 推得,贝叶斯收缩到 0(若样本不足 100 bar)。Kelly 仅作 **缩放因子** 应用于 vol-target 仓位之上,不允许其放大。

### 4.3 跨标的 ERC

当 $\geq 3$ 个标的开仓时,迭代求解使 $w_i\cdot(\Sigma w)_i$ 相等的权重(Cyclical Coordinate Descent)。协方差用 Ledoit-Wolf 收缩(`shrink=0.2`)估计,避免病态。

### 4.4 杠杆护栏

* 单标的:`|N_i| ≤ max_leverage_per_symbol × Equity`(默认 2×)
* 组合 gross:`Σ|N_i| ≤ max_gross_leverage × Equity`(默认 3×)

---

## 5. 离场逻辑

### 5.1 Chandelier Exit(吊灯止损)

$$ \text{LongStop}_t = \max_{s\in[t-N,t]}H_s - m\cdot \mathrm{ATR}_N(t) $$

只 **向有利方向移动**(trail)。$N=22$, $m=3.0$ 是 Chuck LeBeau 的经典参数,在 1m K 线略保守,避免噪声。

### 5.2 Parabolic SAR

加速因子 $AF$ 从 0.02 起步、每新高/新低 +0.02、最大 0.20。趋势衰竭末段抓尾段反转。SAR 与 Chandelier **取较紧者** 触发出场。

### 5.3 时间止损

持仓 ≥ `time_stop_bars`(默认 720 即 12h)且 PnL < $0.5\sigma$,平仓释放保证金。理论:趋势若未在期望时长内兑现,价值期望折现到 0。

---

## 6. 微观结构与执行

### 6.1 Hyperliquid 撮合特性

* L1 EVM 链 CLOB,出块 ~200ms。订单延迟 = 网络 + 签名 + 撮合 ≈ 300-800ms。
* 每对 (sz_decimals, px_decimals) 满足 `pxDec + szDec = 6`(perps);价格须 5 位有效数字。任何超精度会被 **整笔拒单**。
* Funding 每 1h 结算,趋势同向需扣减:$\text{Edge}_{\text{net}} = \text{Edge}_{\text{raw}} - |\text{funding}|$。

### 6.2 Maker / Taker 决策

我们默认 **Post-Only(ALO)** 在 BBO ± `maker_offset_ticks` 挂单。优点:rebate -1bp,无 taker 3.5bp 成本。`maker_timeout_s`(默认 2s)未成交则撤单 + IOC fallback,保证信号衰减前完成调仓。

### 6.3 滑点模型

回测中用 book-walk(`backtest/slippage_model.py`):线性吃多档报价直到填满 notional。实盘中我们**不预估**滑点,直接交由订单簿;但通过订单切片 `slice_max_pct_of_book` 控制单笔吃单 ≤ 15% 的前 5 档累计深度。

---

## 7. 风险控制护栏(Defense in Depth)

| 层 | 名称 | 触发 | 动作 |
|---|---|---|---|
| L1 | Equity Floor | Equity < `equity_floor_usd` | KILL,平所有仓 |
| L2 | Per-Symbol DD | 单标的回撤 > 5% | 该标的 24h Cooldown |
| L3 | Daily Loss | 当日 PnL < -3% | KILL |
| L4 | System Health | WS > 30s 无消息 / Clock drift > 500ms | BLOCK 新单 |
| L5 | Black Swan | 1m 收益率 |z| > 8 | 全市场 30min Cooldown |

所有护栏 **fail-closed**:任何评估抛异常 → 拒绝下单。

---

## 8. 参数综述与默认值

| 模块 | 参数 | 默认 | 说明 |
|---|---|---|---|
| Kalman | $Q_\mu, Q_\nu, R$ | 1e-7, 1e-9, 1e-4 | 1m bar |
| Momentum | half_lives | [16, 64, 256] | bars |
| Momentum | weights | [0.4, 0.4, 0.2] | sum=1 |
| Volatility | yz_window, atr_window, β | 48, 14, 0.7 | |
| Regime | ADX 阈值 | 20 | 趋势确认 |
| Sizing | target_annual_vol | 0.30 | 30% σ* |
| Sizing | kelly_fraction | 0.25 | Quarter-Kelly |
| Sizing | max_lev_per_sym, gross | 2, 3 | × Equity |
| Exit | chandelier N, m | 22, 3.0 | |
| Exit | time_stop_bars | 720 | 12h on 1m |
| Risk | daily_loss_limit_pct | 3.0 | KILL |
| Exec | rebalance_every_n_bars | 5 | 5min on 1m |
| Exec | maker_timeout_s | 2.0 | IOC fallback |

---

## 9. 实盘前必须的研究步骤

1. **历史数据回测**:`trend-hl backtest --symbol BTC --days 60`
2. **稳健性扫描**:扫描 (`half_lives`, `target_vol`, `m`) 网格,检查 Sharpe 高原而非脊
3. **WFA 滚动验证**:每 14 天一段,前 7 天调参后 7 天 OOS
4. **Paper 7+ 天**:`trend-hl paper`,验证 WS 稳定性、订单成交率、滑点分布
5. **小金额 testnet**:Hyperliquid testnet 跑 1-2 天
6. **小金额主网**:`equity_floor_usd` 设为低值,先用 $200-500 跑一周

---

## 10. 当前实现与理论的对应关系

理论只有落到代码才有意义。下面把主要概念映射到当前仓库:

| 理论模块 | 代码位置 | 输入 | 输出 |
|---|---|---|---|
| Kalman 趋势 | `signals/kalman_trend.py` | close 序列 | 趋势速度、SNR 类信息 |
| 多周期动量 | `signals/momentum_bands.py` | 收益率序列 | 动量强度 |
| 波动率 | `signals/volatility.py` | OHLC | `sigma_bar` 等风险尺度 |
| 市态过滤 | `signals/regime.py` | OHLC/收益序列 | 趋势/震荡判断 |
| 信号合成 | `signals/signal_engine.py` | 以上所有信号 | `Signal(direction,strength,metadata)` |
| 仓位 sizing | `risk/sizing.py` | 信号、权益、波动率、权重 | 目标数量和 notional metadata |
| 风控硬门 | `risk/gates.py` | 权益、日亏损、WS、时钟、z-score | ALLOW/BLOCK/KILL |
| 退出逻辑 | `risk/exits.py` | 持仓、OHLC、ATR | 是否平仓 |
| 策略编排 | `strategy/trend_follower.py` | bars、account、books | targets |
| 执行 | `execution/order_router.py` 和 `execution/executor.py` | targets、book、meta | maker/IOC orders |

一个重要工程事实:当前 live/paper 触发调仓不是每根所有标的 K 线都做一次,而是主标的每累计 `rebalance_every_n_bars` 根 bar 触发一次 `_rebalance()`。默认主标的是 `universe.yaml` 里第一个启用标的,通常是 BTC。

## 11. 参数不是旋钮魔法

新手最容易犯的错误是看到收益不理想就随便调参数。下面是参数变化的真实含义:

| 参数 | 调大后通常发生什么 | 风险 |
|---|---|---|
| `target_annual_vol` | 仓位整体变大 | 收益和回撤同时放大 |
| `max_gross_leverage` | 允许组合总敞口更大 | 极端行情下亏损更快 |
| `kelly_fraction` | 模型允许时更激进 | Kelly 对估计误差极敏感 |
| `min_signal_strength` | 更难开仓 | 可能错过趋势 |
| `snr_threshold` | Kalman 更保守 | 信号更少、更晚 |
| `chandelier_atr_mult` | 止损更宽 | 单笔亏损可能变大 |
| `rebalance_every_n_bars` | 换手降低 | 反应变慢 |
| `slice_max_pct_of_book` | 单笔吃深度比例更高 | 滑点和市场冲击更大 |

判断参数好坏,不要问“哪个参数收益最高”,而要问:

1. 它附近的参数是否也表现相近。
2. 它是否只在一个短窗口有效。
3. 它是否让回撤超过你的真实承受能力。
4. 它是否让交易频率高到手续费吞掉收益。
5. 它在 paper 中是否仍保持类似行为。

## 12. 常见误解

### 12.1 “信号为正就一定会买”

不一定。信号只是输入之一。风控、波动率、最小名义金额、订单簿、已有仓位都会影响最终订单。

### 12.2 “没有交易说明系统坏了”

不一定。趋势策略在震荡市保持空仓是正常行为。先看 `signals_log`、heartbeat 的 bars 数和风控原因。

### 12.3 “回测 Sharpe 高就可以 live”

不可以。回测没有真实盘口排队、网络中断、API 拒单、实盘心理压力和 funding 冲击。Paper 是必要环节。

### 12.4 “提高杠杆只是放大收益”

提高杠杆同时放大亏损、回撤、强平风险和心理压力。策略边际优势不够厚时,杠杆会更快暴露缺陷。

### 12.5 “止损越紧越安全”

不一定。止损太紧会在噪声中反复小亏,让趋势还没开始就被洗掉。止损太宽又会扩大单笔亏损,所以必须结合波动率和回测/paper 观察。

## 13. 从理论到上线的学习路径

建议你按以下顺序掌握系统:

1. 能解释 `long`、`short`、`notional`、`leverage`、`drawdown`。
2. 能运行 7 天和 30 天回测,并解释每个指标。
3. 能在 paper 中查到 `signals_log`、`equity_snapshots`、`fills`。
4. 能解释为什么某一次没有下单。
5. 能手动停止服务、撤单和平仓。
6. 能说清楚调大一个参数会带来什么代价。
7. 能接受策略长时间不交易或短期亏损。

如果这些做不到,理论还没有真正变成操作能力,不建议 live。

---

## 参考文献

* Baz et al. (2015). *Dissecting Investment Strategies in the Cross Section and Time Series*. SSRN 2695101.
* Yang & Zhang (2000). *Drift-Independent Volatility Estimation Based on High, Low, Open, and Close Prices*. Journal of Business.
* LeBeau, C. (1995). *Computer Analysis of the Futures Markets*. McGraw-Hill.
* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems*.
* Ledoit & Wolf (2004). *Honey, I Shrunk the Sample Covariance Matrix*. JPM.
* Kelly, J. L. (1956). *A New Interpretation of Information Rate*.
