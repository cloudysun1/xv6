# 04 · 运维 Runbook:按症状排障

> Runbook 的用途是在出问题时减少慌乱。每一节都按“症状、影响、诊断、处理、复盘”组织。除非你非常确定,资金风险优先级永远高于保持服务运行。

## 1. 先做 60 秒总览

任何问题出现时,先不要立刻重启。先收集状态:

```bash
sudo systemctl status trend-hl --no-pager
journalctl -u trend-hl --since '30 min ago' --no-pager | tail -200
tail -100 data/logs/errors.log
sqlite3 data/orders.sqlite '.tables'
sqlite3 data/orders.sqlite 'SELECT equity,margin_used,free_margin,positions_json FROM equity_snapshots ORDER BY ts_ms DESC LIMIT 5;'
```

这些命令分别回答:

| 命令 | 回答的问题 |
|---|---|
| `systemctl status` | 服务是否还活着、是否一直重启 |
| `journalctl` | systemd 层面的近期日志 |
| `errors.log` | Python 运行时错误 |
| `.tables` | SQLite 文件是否存在且可读 |
| `equity_snapshots` | 最近账户权益和仓位是否被写入 |

如果怀疑资金风险,同时打开 Hyperliquid Web UI,以 Web UI 为最终资金状态准绳。

## 2. 系统进入 KILL 状态

### 症状

- 日志出现 `KILL-SWITCH ENGAGED`。
- 目标仓位变为 0 或不再开新仓。
- 通知通道收到 KILL 或错误告警。

### 影响

KILL 是最严重的风控状态。当前实现中,`RiskManager.compute_target()` 在 KILL 时会把目标仓位设为 0,尝试让执行器平到空仓。但是否真的平掉,取决于订单能否成功提交和成交。因此 KILL 后必须人工核对 Web UI。

### 诊断

```bash
journalctl -u trend-hl --since '2 hours ago' --no-pager | grep -Ei 'KILL|equity_floor|daily_loss|RiskGate|gate:'
sqlite3 data/orders.sqlite 'SELECT equity,margin_used,free_margin,positions_json FROM equity_snapshots ORDER BY ts_ms DESC LIMIT 20;'
sqlite3 data/orders.sqlite 'SELECT symbol,direction,strength,target_leverage,metadata_json FROM signals_log ORDER BY ts_ms DESC LIMIT 20;'
```

常见原因:

| 原因 | 判断方式 | 说明 |
|---|---|---|
| `equity_floor` | 权益低于 `EQUITY_FLOOR_USD` | 资金下限保护 |
| `daily_loss_limit` | 当日权益较 UTC 日初亏损超过阈值 | 默认 -3% |
| 手动或代码触发 kill | 日志中有具体 reason | 需要看上下文 |

### 处理

1. 打开 Hyperliquid Web UI。
2. 检查 open orders,必要时全部撤单。
3. 检查 positions,必要时手动平仓。
4. 停服务:

```bash
sudo systemctl stop trend-hl
```

5. 判断原因是否已经解除。不要只靠重启绕过 KILL。
6. 如需继续,先改为 paper 复现,再 live。

### 复盘

记录 KILL 触发时间、触发权益、当日亏损、当时持仓、订单、市场波动,并判断是否需要降低 `MAX_GROSS_LEVERAGE`、`DAILY_LOSS_LIMIT_PCT` 或标的数量。

## 3. 服务反复重启

### 症状

- `systemctl status` 显示 activating / auto-restart。
- `journalctl` 反复出现启动日志。
- `data/logs/trend_hl.log` 不断重新写 `Logging configured`。

### 诊断

```bash
sudo systemctl status trend-hl --no-pager
journalctl -u trend-hl --since '30 min ago' --no-pager | tail -300
tail -200 data/logs/errors.log
```

高频原因:

| 现象 | 可能原因 | 处理 |
|---|---|---|
| pydantic validation error | `.env` 地址或私钥格式错 | 检查 `HL_ACCOUNT_ADDRESS` 和 `HL_API_SECRET` 长度 |
| `universe file not found` | 工作目录或 `TREND_HL_UNIVERSE_FILE` 错 | 确认 `WorkingDirectory` 是仓库根目录 |
| import error | 虚拟环境没装好 | 重新 `pip install -e ".[dev,backtest]"` |
| permission denied | systemd 用户无权写 data | `sudo chown -R trader:trader /home/trader/trend-hl/data` |

### 处理

先停掉自动重启,避免刷屏:

```bash
sudo systemctl stop trend-hl
```

手动在同一用户下启动一次,错误会更清楚:

```bash
cd ~/trend-hl
source .venv/bin/activate
trend-hl paper
```

修好后再交给 systemd:

```bash
sudo systemctl start trend-hl
```

## 4. WebSocket 反复重连或不健康

### 症状

- 日志出现 `WS dropped`、`WS inactivity timeout`、`reconnecting`。
- 风控原因出现 `ws_unhealthy`。
- 心跳中 bars 不增长。

### 影响

WebSocket 不健康时,策略可能没有最新行情和订单簿。当前风控会 BLOCK 新单,这是正确行为。

### 诊断

```bash
ping -c 5 api.hyperliquid.xyz
curl -sS -X POST https://api.hyperliquid.xyz/info -H 'content-type: application/json' -d '{"type":"meta"}' | head -c 200
journalctl -u trend-hl --since '1 hour ago' --no-pager | grep -Ei 'WS|websocket|resync|heartbeat'
```

判断:

| 结果 | 含义 |
|---|---|
| REST 也失败 | 服务器网络或 DNS 问题 |
| REST 成功但 WS 失败 | WebSocket 被中间网络影响,或服务端临时异常 |
| 过几分钟自动恢复 | 代码重连机制生效 |
| 超过 30 分钟不恢复 | 考虑换机房或服务商 |

### 处理

短时波动可观察 5 分钟。长期异常:

```bash
sudo systemctl restart trend-hl
```

如果仍异常,检查 VPS 供应商网络状态,考虑换 DNS 或机房,必要时停机手动管理持仓。

## 5. 时钟漂移告警

### 症状

- 日志出现 `clock_drift`。
- 风控 BLOCK 新单。

### 诊断

```bash
timedatectl
chronyc tracking
chronyc sources -v
```

### 处理

```bash
sudo systemctl restart chrony
sudo chronyc makestep
chronyc tracking
```

如果默认 NTP 源不可用,编辑:

```bash
sudo nano /etc/chrony/chrony.conf
```

加入:

```text
pool time.cloudflare.com iburst
pool time.google.com iburst
```

然后:

```bash
sudo systemctl restart chrony
```

## 6. 订单连续 REJECTED

### 症状

- 日志或 SQLite 中订单状态为 `REJECTED`。
- Web UI 持仓没有按目标变化。
- 心跳 orders 增长,但 fills 不增长。

### 诊断

当前代码有 `orders` 表和 `insert_order()` 方法,但 live/paper 主循环不保证每个 OrderAck 都写入该表。如果下面查询为空,不要直接判断“没有拒单”,还要结合 `journalctl`、`data/logs/errors.log` 和 Hyperliquid Web UI。

```bash
sqlite3 data/orders.sqlite "SELECT ts_ms,symbol,side,size,price,order_type,tif,status,raw_json FROM orders ORDER BY ts_ms DESC LIMIT 20;"
journalctl -u trend-hl --since '1 hour ago' --no-pager | grep -Ei 'REJECTED|place_order|OrderAck|error|precision|margin|unauthorized'
```

常见原因:

| `raw_json` 或现象 | 含义 | 处理 |
|---|---|---|
| unauthorized / 401 | Agent 未授权或网络不匹配 | 在对应主网/测试网重新授权 Agent |
| insufficient margin | 保证金不足 | 降杠杆、减标的、加保证金 |
| min notional / size too small | 订单低于最小名义金额或数量 | 提高资金、减少标的分散、调高目标强度才交易 |
| precision / tick | 价格或数量精度问题 | 重启刷新 meta;若仍失败检查 `precision.py` |
| post only would cross | maker 挂单会立即吃单 | 正常情况下 IOC fallback 会处理,持续出现需看订单簿 |
| rate limit | API 限流 | 降低 rebalance 频率或检查异常循环 |

### 处理

1. 如果是 live,先看 Web UI 是否有残留 open orders。
2. 确认 `.env` URL 与钱包授权网络一致。
3. 重启刷新交易所 meta:

```bash
sudo systemctl restart trend-hl
```

4. 如果仍连续拒单,停 live 改 paper,避免盲目重试。

## 7. 信号长时间 FLAT 或没有订单

### 症状

- `signals_log` 中方向或强度接近 0。
- 没有订单提交。
- 持仓长期为空。

### 先分清正常和异常

趋势系统不应该时时刻刻交易。以下情况可能正常:

1. 刚启动,历史 warm-up 还不够。
2. 市场震荡,ADX/Hurst 或信号门控削弱仓位。
3. 信号强度低于 `min_signal_strength=0.15`。
4. 目标名义金额低于 `min_notional_usd=11.0`。
5. 当前标的没有最新订单簿。

### 诊断

```bash
sqlite3 data/orders.sqlite 'SELECT symbol,direction,strength,target_leverage,metadata_json FROM signals_log ORDER BY ts_ms DESC LIMIT 50;'
journalctl -u trend-hl --since '2 hours ago' --no-pager | grep -Ei 'signal|gate|ws_unhealthy|clock_drift|heartbeat'
```

判断:

| 现象 | 说明 |
|---|---|
| `signals_log` 没有记录 | 策略可能还没触发 rebalance,或没有足够 bars |
| 有信号但没有订单 | 目标仓位可能太小、风控 BLOCK、无订单簿或 meta |
| 有订单但无成交 | maker 没成交且 fallback 可能被拒,查 orders |

不要为了“让它交易”直接降低所有阈值。先延长观察窗口到数小时,确认系统在 heartbeat 中 bars 持续增长。

## 8. 成交与 SQLite 不一致

### 症状

- Web UI 看到成交,但 `fills` 表没有对应记录。
- SQLite 中权益和 Web UI 不一致。

### 当前实现事实

当前 live/paper 主循环在每次 rebalance 后调用 `adapter.fetch_recent_fills()` 拉最近 5 分钟成交并写入 `fills`。这不是逐笔 user fill WebSocket 持久订阅,因此极端情况下可能漏记或延迟记录。

### 诊断

```bash
sqlite3 data/orders.sqlite 'SELECT * FROM fills ORDER BY ts_ms DESC LIMIT 50;'
sqlite3 data/orders.sqlite 'SELECT * FROM orders ORDER BY ts_ms DESC LIMIT 50;'
journalctl -u trend-hl --since '1 hour ago' --no-pager | grep -Ei 'fill|fetch_recent_fills|error|exception'
```

如果 `orders` 表为空,优先使用 `fills`、`equity_snapshots`、日志和 Web UI 对账。订单表为空是当前实现边界,不是 SQLite 损坏的证据。

### 处理

1. 以 Hyperliquid Web UI 和官方成交导出为准。
2. 停止 live,避免审计不清时继续交易。
3. 导出交易所成交 CSV,与 `fills` 表对账。
4. 如果经常发生,需要增强代码为启动时和重连后做更长窗口的 REST reconcile。

## 9. SQLite database is locked

### 症状

- `errors.log` 出现 `database is locked`。
- 查询或写入 SQLite 失败。

### 原因

SQLite 是单文件数据库。长时间交互式查询、外部工具锁住文件、异常退出后的 WAL 状态,都可能造成锁冲突。

### 处理

```bash
sudo systemctl stop trend-hl
sqlite3 data/orders.sqlite 'PRAGMA wal_checkpoint(TRUNCATE);'
sqlite3 data/orders.sqlite 'PRAGMA integrity_check;'
sudo systemctl start trend-hl
```

如果 `integrity_check` 不是 `ok`,先备份文件,再考虑从备份恢复。

## 10. 日志不更新或健康检查失败

### 症状

- Docker healthcheck unhealthy。
- `data/logs/trend_hl.log` 修改时间超过 180 秒。
- 心跳没有新记录。

### 当前健康检查逻辑

`scripts/healthcheck.py` 只检查 `TREND_HL_DATA_DIR/logs/trend_hl.log` 是否存在且最近修改时间小于 `HEALTHCHECK_MAX_AGE_S`,默认 180 秒。它不直接检查交易所连接或下单能力。

### 诊断

```bash
ls -l data/logs/trend_hl.log
docker ps
docker inspect --format='{{json .State.Health}}' trend-hl
docker logs --tail=200 trend-hl
```

### 处理

1. 确认容器或 systemd 服务是否还在。
2. 确认 `TREND_HL_DATA_DIR` 和 volume 挂载一致。
3. 看 `errors.log` 或容器 stdout。
4. 如果服务卡死,停机后重启。

## 11. 升级后行为异常

### 症状

- 升级后订单、信号、日志格式明显变化。
- 测试失败但服务仍被启动。
- 回测结果和之前差异巨大。

### 处理

先停服务:

```bash
sudo systemctl stop trend-hl
```

查看最近提交:

```bash
cd ~/trend-hl
git log --oneline -10
git status --short
```

如果要回到某个已知可用版本:

```bash
git checkout <last-good-sha>
source .venv/bin/activate
pip install -e ".[dev,backtest]"
pytest -q
sudo systemctl start trend-hl
```

不要在持仓不清楚时盲目升级或回滚。先确认 Web UI 持仓和 open orders。

## 12. 紧急完全停机和平仓

### 最稳妥流程

1. 停服务。
2. 打开 Hyperliquid Web UI。
3. 撤掉所有 open orders。
4. 手动平掉所有 positions。
5. 如果怀疑私钥泄露,撤销 Agent。

systemd:

```bash
sudo systemctl stop trend-hl
```

Docker:

```bash
cd ~/trend-hl/docker
docker compose down
```

优先使用 Web UI,因为它最直观、最少依赖本地代码状态。命令行脚本只有在你确认代码和凭据可用、并且理解 reduce-only 风险时才使用。

运行前先查账户:

```bash
source .venv/bin/activate
python - <<'PY'
import asyncio
from trend_hl.config.settings import load_settings
from trend_hl.exchange.hyperliquid_adapter import HyperliquidAdapter

async def main():
    settings = load_settings()
    adapter = HyperliquidAdapter(settings.hl())
    await adapter.connect()
    account = await adapter.fetch_account()
    print(account)
    await adapter.close()

asyncio.run(main())
PY
```

如果输出都看不懂,不要继续写自动平仓脚本,改用 Web UI。

## 13. 事故分级

| 等级 | 定义 | 目标响应 |
|---|---|---|
| P0 | 真实资金可能继续扩大损失、私钥疑似泄露 | 立即停机、手动撤单平仓、撤 Agent |
| P1 | 服务宕机、无法接收行情、连续拒单 | 30 分钟内恢复或保持停机 |
| P2 | 审计数据缺失、心跳异常、paper 不稳定 | 当日修复或记录 issue |
| P3 | 文档不清、指标希望增强、参数研究 | 纳入后续优化 |

## 14. 复盘模板

每次异常后记录:

```text
时间 UTC:
模式: paper / live
影响标的:
发现方式: 日志 / 通知 / Web UI / 手动巡检
直接症状:
资金影响:
根因:
临时处理:
永久修复:
需要新增测试或文档:
```

