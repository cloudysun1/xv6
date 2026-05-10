# 99 · 文档迭代审计

本文记录本次文档优化的每一轮目标、改动和自我评估。它不是用户手册的一部分,而是用来保证“每轮都有明确改进点,并且改动落在 docs 中”。

## 第 1 轮:入口与事实校准

### 分析

原有文档从理论、架构、部署、运维、回测分文件展开,但缺少一份面向完全新手的入口手册。读者如果不知道 paper/live/backtest 区别、`.env` 字段含义、SQLite 文件位置、标的池在哪里,会在进入部署文档前就卡住。

同时发现若干需要在后续轮次修正的实现不一致:

| 文档说法 | 当前代码事实 | 后续处理 |
|---|---|---|
| SQLite 查询使用 `data/trend_hl.sqlite` | `app.py` 连接 `data/orders.sqlite` | 第 2 轮修正部署和 Runbook |
| 回测参数包含 `--initial-equity` | CLI 当前只有 `--symbol`, `--interval`, `--days` | 第 2 轮修正回测指南 |
| WFA 示例包含 `--start-offset-days` | CLI 当前没有该参数 | 第 2 轮改为说明需要扩展 CLI 或手动修改时间窗口 |
| 部署文档默认 `TREND_HL_ENV=live` | CLI 命令决定实际模式,该变量更多是运行意图配置 | 第 2 轮解释清楚 |

### 修改

新增 `docs/00_getting_started.md`,覆盖:

1. 系统做什么以及完整交易链路。
2. backtest、paper、live 三种模式的区别。
3. 基础术语表。
4. 关键文件、日志、SQLite、bar 数据目录。
5. 本地安装、`.env` 配置、标的池配置。
6. 第一次回测、第一次 paper、第一次 live 的成功标志。
7. 上线前最低验收清单。
8. 常用日志和 SQLite 查询。
9. 第一次使用最常见卡点。
10. 推荐文档阅读顺序。

### 自我评估

第 1 轮解决了“没有入口”和“读者不知道从哪开始”的问题,但还没有系统性扩写原有五份文档。下一轮重点是把部署、回测、运维、架构、理论文档按真实代码细节修正并扩展。

## 第 2 轮:操作文档和理论架构深度扩写

### 分析

第 2 轮重点检查“用户照着文档操作时会不会被带偏”。对照代码后发现,最需要修正的是运行命令、SQLite 文件名、回测能力边界、Docker 默认 live 命令、以及当前审计写入并没有完整覆盖 orders 表。

### 修改

更新 `docs/03_deployment.md`:

1. 按部署目标、资源准备、Agent Wallet、VPS 初始化、安装、`.env`、标的池、回测、paper、systemd、Docker、升级、备份、live 前清单、紧急停机重写。
2. 明确 `TREND_HL_ENV` 只是 settings 字段,实际运行模式由 CLI 子命令决定。
3. 明确当前 SQLite 文件是 `data/orders.sqlite`。
4. 明确 Dockerfile 默认 `scripts/run_live.py`,首次容器部署应改为 paper 或覆盖 command。
5. 补充每一步成功标志和失败时先查什么。

更新 `docs/04_runbook.md`:

1. 改成按症状排障:KILL、服务重启、WS、时钟、拒单、信号为空、成交审计、SQLite 锁、健康检查、升级异常、紧急停机。
2. 所有 SQLite 查询修正为 `data/orders.sqlite` 和当前表字段。
3. 明确 KILL 后仍必须人工核对 Web UI,程序停止也不等于自动平仓。
4. 明确当前 fill 记录依赖 rebalance 后拉最近成交,不是独立 user fills stream。

更新 `docs/05_backtest_guide.md`:

1. 列出当前 CLI 只支持 `--symbol`, `--interval`, `--days`。
2. 删除或纠正当前未实现的 `--initial-equity`, `--start-offset-days`, 自动报告文件等说法。
3. 解释当前回测从 Hyperliquid `candleSnapshot` 拉 K 线,并使用合成 L2 book。
4. 增加指标解释、短样本 CAGR 误区、稳健性检查、回测与 paper 对齐方法。

更新 `docs/02_architecture.md`:

1. 按目录职责、运行模式、启动顺序、实时数据流、回测数据流、配置流、信号风险衔接、执行层、持久化、后台任务、故障边界重写。
2. 记录当前已知边界:回测单标的、`.env` 覆盖范围有限、orders 表写入路径需要增强、fill 持久化不是独立 stream。

更新 `docs/01_theory.md`:

1. 增加从零开始的术语、价格到订单链路、对数价格、趋势追踪假设、永续合约风险。
2. 增加理论模块到代码文件的映射。
3. 增加参数解释和常见误解,避免读者把参数当成收益旋钮。

### 自我评估

第 2 轮已经把主要事实错误和操作断点补齐,文档能覆盖从本地安装、回测、paper、部署、排障到理论理解的主路径。仍需第 3 轮做一致性扫描:检查旧路径、旧参数、重复或矛盾描述,并补一个最终查漏清单。

## 第 3 轮:一致性审校与边界补丁

### 分析

对 docs 目录执行一致性扫描,重点搜索旧 SQLite 文件名、未实现 CLI 参数、旧报告目录、README 文档索引和订单审计写入路径。扫描结果表明旧路径和旧参数已经不再作为真实可用能力出现,但发现一个更细的问题:文档多处把 `orders` 表当作完整订单审计来源,而当前实时主循环没有保证每个 OrderAck 写入该表。

### 修改

1. 在 `docs/00_getting_started.md` 中把 `data/orders.sqlite` 解释为 SQLite 审计库,并注明当前主要写权益、信号和成交;`orders` 表 schema 存在,但实时写入覆盖仍有限。
2. 在 `docs/03_deployment.md` 的备份章节中修正 `data/orders.sqlite` 的内容描述,避免承诺完整订单审计。
3. 在 `docs/04_runbook.md` 的订单拒绝和成交对账章节加入说明:如果 `orders` 表为空,应结合日志、`fills`、`equity_snapshots` 和 Hyperliquid Web UI 判断。
4. 更新 `README.md` 文档索引,加入 `00_getting_started.md`, `05_backtest_guide.md`, `99_documentation_audit.md`。

### 自我评估

第 3 轮后,文档的主路径、命令、文件名、当前能力边界和排障入口已经与代码一致。剩余明显优化空间已经从“文档缺失/错误”转为“代码能力可增强”,例如完整订单 ack 持久化、回测 start/end 参数、多标的回测、报告文件输出、配置 overlay。这些更适合作为后续代码迭代,而不是继续在文档里补丁式解释。
