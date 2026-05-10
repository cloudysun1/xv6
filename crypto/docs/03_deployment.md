# 03 · 部署教程:从空服务器到可值守运行

> 本文面向 Ubuntu 22.04/24.04 VPS。它会一步一步说明为什么要做每个操作、怎么判断成功、失败时先看哪里。实盘交易有资金风险,部署成功不等于策略适合上线。

## 1. 部署前先确认目标

部署不是“把程序跑起来”这么简单。对交易系统来说,一个合格部署至少要满足:

1. 程序能稳定访问 Hyperliquid REST 和 WebSocket。
2. 服务器时间接近 UTC 标准时间,否则订单和风控判断会失真。
3. 私钥不出现在日志、git、shell 历史或多人可读文件中。
4. 服务崩溃后能自动重启,但不会无限制扩大风险。
5. 你能在 5 分钟内停止服务、查看日志、手动平仓、撤销 Agent。

本文按推荐顺序部署:准备 Agent Wallet,初始化 VPS,安装项目,配置 `.env` 和标的池,先跑测试和回测,连续运行 paper,再用 systemd 或 Docker 托管。最后才考虑 live。

## 2. 资源和账号准备

| 项 | 推荐值 | 解释 |
|---|---|---|
| VPS | 2 vCPU,4 GB RAM,30 GB SSD | Python、Polars、WebSocket、日志和 SQLite 都需要一定余量 |
| 系统 | Ubuntu 22.04 LTS 或 24.04 LTS | 文档命令以 Ubuntu 为准 |
| 机房 | 网络稳定优先,其次考虑延迟 | 趋势策略不是高频抢单,稳定性比极限延迟重要 |
| Python | 3.11 或 3.12 | 项目要求 `>=3.11,<3.13` |
| 主钱包 | Hyperliquid 主账户地址 | 写入 `HL_ACCOUNT_ADDRESS` |
| Agent Wallet | Hyperliquid API/Agent 私钥 | 写入 `HL_API_SECRET`,不要写主钱包私钥 |
| 通知 | Telegram 或 Discord 可选 | 心跳、停止、告警会通过 notifier 发送 |

## 3. 创建 Hyperliquid Agent Wallet

Agent Wallet 是给程序交易用的钱包。它通过主钱包授权,可以签交易指令,但通常不能提现。即便如此,它仍然可以造成交易亏损,所以必须按私钥标准保护。

步骤:

1. 打开 `https://app.hyperliquid.xyz`。
2. 用 MetaMask、Rabby 或其他钱包连接主钱包。
3. 进入 API / Agent Wallet 页面。
4. Generate Agent Wallet。
5. 保存弹出的 `0x` 开头私钥。它只显示一次。
6. 记下主钱包地址,这才是 `.env` 里的 `HL_ACCOUNT_ADDRESS`。
7. 在 Web UI 中 Approve Agent。

核对:

| 项 | 应该是什么 |
|---|---|
| `HL_ACCOUNT_ADDRESS` | 主钱包地址,`0x` 加 40 位十六进制,总长 42 字符 |
| `HL_API_SECRET` | Agent 私钥,`0x` 加 64 位十六进制,总长 66 字符 |
| 不应填写 | 主钱包私钥 |

如果你不确定哪个是主钱包、哪个是 Agent,先不要 live。错误填写主钱包私钥是严重安全事故。

## 4. 初始化 VPS

以下命令假设你以 root 登录了一台新服务器。

```bash
adduser trader
usermod -aG sudo trader
ufw allow OpenSSH
ufw enable
su - trader
```

解释:

| 命令 | 作用 |
|---|---|
| `adduser trader` | 创建普通用户,避免长期用 root 跑交易程序 |
| `usermod -aG sudo trader` | 允许必要时执行 sudo |
| `ufw allow OpenSSH` | 防止启用防火墙后把自己锁在服务器外 |
| `ufw enable` | 开启基础防火墙 |

安装系统依赖:

```bash
sudo apt update
sudo apt -y upgrade
sudo apt -y install build-essential git curl ca-certificates gnupg sqlite3 chrony tzdata python3 python3-venv python3-dev
sudo timedatectl set-timezone UTC
sudo systemctl enable --now chrony
```

检查时间同步:

```bash
timedatectl
chronyc tracking
```

成功标志:

1. `timedatectl` 显示 `Time zone: Etc/UTC` 或 `UTC`。
2. `chronyc tracking` 能看到 reference 和 offset。
3. 没有 `System clock synchronized: no`。

如果服务器时间漂移,系统风控会 BLOCK 新单。当前默认阈值在 `RiskGateParams.clock_drift_max_ms` 中是 500ms。

## 5. 拉代码和安装依赖

```bash
git clone <YOUR-REPO-URL> ~/trend-hl
cd ~/trend-hl
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e ".[dev,backtest]"
```

检查 CLI:

```bash
trend-hl --help
```

应能看到三个子命令:

```text
live
paper
backtest
```

运行测试:

```bash
pytest -q
```

如果 `trend-hl` 找不到,通常是虚拟环境没有激活。重新执行:

```bash
source ~/trend-hl/.venv/bin/activate
```

## 6. 配置 `.env`

复制模板:

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

`chmod 600` 表示只有文件所有者能读写。交易私钥不应该让同机器其他用户读取。

最小配置:

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

变量解释:

| 变量 | 当前代码如何使用 | 注意事项 |
|---|---|---|
| `HL_ACCOUNT_ADDRESS` | `Settings.hl()` 传给 Hyperliquid SDK 查询账户和下单账户 | 必须是主钱包地址 |
| `HL_API_SECRET` | `Account.from_key()` 构造 Agent 签名账户 | 必须是 Agent 私钥 |
| `HL_API_URL` | REST 和 SDK base URL | 主网/测试网要与钱包授权匹配 |
| `HL_WS_URL` | WebSocket 行情地址 | 与 REST 网络保持一致 |
| `HL_NETWORK` | 记录网络名称 | 当前实际连接主要由 URL 决定 |
| `TREND_HL_ENV` | pydantic settings 读取运行意图 | 实际模式由 `trend-hl live/paper/backtest` 子命令决定 |
| `TREND_HL_LOG_LEVEL` | 传给日志配置 | 排障可临时改为 `DEBUG` |
| `TREND_HL_DATA_DIR` | 日志、SQLite、bar 数据根目录 | 默认 `./data` |
| `EQUITY_FLOOR_USD` | 覆盖风险参数 `equity_floor_usd` | 权益低于该值会 KILL |
| `DAILY_LOSS_LIMIT_PCT` | 覆盖每日亏损限制 | `3.0` 表示 -3% |
| `MAX_GROSS_LEVERAGE` | 覆盖组合总杠杆上限 | 新手可设更低 |

测试网配置示例:

```dotenv
HL_API_URL=https://api.hyperliquid-testnet.xyz
HL_WS_URL=wss://api.hyperliquid-testnet.xyz/ws
HL_NETWORK=testnet
```

测试网需要在测试网 Web UI 创建和授权 Agent,不能直接复用主网授权结果。

## 7. 配置标的池

打开:

```bash
nano src/trend_hl/config/universe.yaml
```

默认内容大致为:

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

建议:

1. 第一次 paper 可以保留默认。
2. 第一次 live 建议只启用 BTC 或 BTC/ETH。
3. 不要在不了解流动性时启用小币种。
4. `symbol` 必须与 Hyperliquid `meta` 返回名称一致。

## 8. 回测烟雾测试

```bash
trend-hl backtest --symbol BTC --interval 1m --days 7
```

当前 CLI 只支持三个参数:

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--symbol` | `BTC` | 单个回测标的 |
| `--interval` | `1m` | K 线周期 |
| `--days` | `7` | 从当前时间向前取多少天 |

成功标志:

1. 没有 HTTP、pydantic、私钥格式异常。
2. 控制台打印 Total Return、CAGR、Sharpe、Sortino、Max DD、Trades、Avg Fee。
3. 如果输出全是 0,先不要判定策略无效,需要看是否交易条件未触发或样本太短。

当前实现直接在控制台打印回测报告,不会自动写 `data/backtest_reports/` 文件。

## 9. Paper 模式试运行

```bash
trend-hl paper
```

paper 模式特点:

1. 使用真实 REST 和 WebSocket 行情。
2. 不向 Hyperliquid 发送真实订单。
3. 使用内存中的 `PaperAdapter` 模拟成交。
4. 默认模拟账户权益是 10000 USDC。
5. 仍会写日志、SQLite 和 bar parquet。

观察至少 10 分钟:

```bash
tail -f data/logs/trend_hl.log
```

成功标志:

| 日志或文件 | 说明 |
|---|---|
| `trend-hl starting in paper mode` | 模式正确 |
| `Loaded meta for ... HL perps` | REST 能取交易所元数据 |
| `WS connected` | WebSocket 已连接 |
| `[heartbeat] equity=... bars=...` | 主循环和心跳正常 |
| `data/orders.sqlite` | SQLite 已创建 |
| `data/bars/<SYMBOL>/<INTERVAL>/` | K 线持久化开始生成 |

查询运行状态:

```bash
sqlite3 data/orders.sqlite '.tables'
sqlite3 data/orders.sqlite 'SELECT * FROM equity_snapshots ORDER BY ts_ms DESC LIMIT 5;'
sqlite3 data/orders.sqlite 'SELECT symbol,direction,strength,target_leverage FROM signals_log ORDER BY ts_ms DESC LIMIT 10;'
```

停止:

```text
Ctrl-C
```

如果 paper 运行 10 分钟没有订单,不一定是错误。默认 `rebalance_every_n_bars=5`,信号还可能被 warm-up、震荡市、最小信号强度、风控 BLOCK 或没有订单簿数据影响。

## 10. systemd 部署

systemd 适合长期运行。它能开机自启、崩溃重启、集中查看日志。

创建服务文件:

```bash
sudo tee /etc/systemd/system/trend-hl.service >/dev/null <<'EOF'
[Unit]
Description=Trend-HL Hyperliquid Trading Bot
After=network-online.target chrony.service
Wants=network-online.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/trend-hl
EnvironmentFile=/home/trader/trend-hl/.env
ExecStart=/home/trader/trend-hl/.venv/bin/trend-hl paper
Restart=always
RestartSec=15
TimeoutStopSec=30
KillSignal=SIGTERM
LimitNOFILE=65536
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/home/trader/trend-hl/data

[Install]
WantedBy=multi-user.target
EOF
```

先用 `paper` 托管。连续稳定后,再把 `ExecStart` 改成:

```ini
ExecStart=/home/trader/trend-hl/.venv/bin/trend-hl live
```

启动:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now trend-hl
sudo systemctl status trend-hl --no-pager
journalctl -fu trend-hl
```

常用命令:

| 命令 | 作用 |
|---|---|
| `sudo systemctl start trend-hl` | 启动 |
| `sudo systemctl stop trend-hl` | 停止 |
| `sudo systemctl restart trend-hl` | 重启 |
| `sudo systemctl status trend-hl --no-pager` | 查看 systemd 状态 |
| `journalctl -u trend-hl --since '1 hour ago'` | 看最近一小时日志 |
| `journalctl -fu trend-hl` | 实时跟踪日志 |

## 11. Docker Compose 部署

Docker 适合希望依赖隔离的人。当前 `docker/Dockerfile` 默认命令是 `python scripts/run_live.py`,也就是容器启动后进入 live 模式。第一次使用前,建议先改成 paper 或临时覆盖命令。

安装 Docker:

```bash
sudo apt -y install docker.io docker-compose-v2
sudo usermod -aG docker trader
newgrp docker
```

构建和启动:

```bash
cd ~/trend-hl/docker
docker compose up -d --build
docker compose logs -f trend-hl
```

重要事实:

| 项 | 当前配置 |
|---|---|
| 环境变量 | `docker-compose.yml` 读取 `../.env` |
| 数据目录 | 宿主机 `../data` 挂载到容器 `/app/data` |
| 健康检查 | `scripts/healthcheck.py` 检查日志文件最近更新时间 |
| 默认命令 | Dockerfile `CMD ["python", "scripts/run_live.py"]` |

如果你想先用 paper,可以临时运行:

```bash
docker compose run --rm trend-hl python scripts/run_paper.py
```

或者修改 compose 的 `command` 为:

```yaml
command: ["python", "scripts/run_paper.py"]
```

## 12. 升级流程

升级前先停服务:

```bash
sudo systemctl stop trend-hl
cd ~/trend-hl
git status --short
git pull
source .venv/bin/activate
pip install -e ".[dev,backtest]"
pytest -q
trend-hl backtest --symbol BTC --interval 1m --days 3
sudo systemctl start trend-hl
```

为什么要先停服务:避免代码升级过程中,正在运行的进程使用旧代码、旧依赖和新文件的混合状态。

如果是 Docker:

```bash
cd ~/trend-hl/docker
docker compose down
git -C .. pull
docker compose up -d --build
docker compose logs -f trend-hl
```

## 13. 备份和恢复

需要备份:

| 路径 | 内容 | 重要性 |
|---|---|---|
| `.env` | 凭据和风险参数 | 极高,但不要放入普通云盘明文备份 |
| `data/orders.sqlite` | SQLite 审计库,当前主要包含成交、权益、信号,订单表写入覆盖仍需代码增强 | 高 |
| `data/bars/` | 实时保存的 K 线 parquet | 中高 |
| `src/trend_hl/config/universe.yaml` | 标的池配置 | 中 |

备份 SQLite:

```bash
mkdir -p ~/trend-hl-backups
sqlite3 data/orders.sqlite ".backup '~/trend-hl-backups/orders-$(date -u +%Y%m%d-%H%M%S).sqlite'"
```

恢复时先停服务,再替换文件:

```bash
sudo systemctl stop trend-hl
cp ~/trend-hl-backups/orders-YYYYMMDD-HHMMSS.sqlite data/orders.sqlite
sudo systemctl start trend-hl
```

## 14. Live 前最后确认

上线前逐条确认:

- [ ] 你已经连续 paper 至少 7 天。
- [ ] 你知道如何在 Hyperliquid Web UI 手动平仓。
- [ ] `sudo systemctl stop trend-hl` 后,Web UI 不再出现新订单。
- [ ] `data/orders.sqlite` 能查询到 `equity_snapshots` 和 `signals_log`。
- [ ] `.env` 权限是 `600`。
- [ ] `EQUITY_FLOOR_USD` 没有高于当前账户权益。
- [ ] `DAILY_LOSS_LIMIT_PCT` 是你愿意真实承受的日亏损。
- [ ] `MAX_GROSS_LEVERAGE` 足够保守。
- [ ] Agent 可以撤销,你知道撤销入口。
- [ ] 你已经读过 `docs/04_runbook.md`。

第一次 live 建议:

1. 只启用 BTC 或 BTC/ETH。
2. 使用小资金。
3. 打开 Web UI 旁观至少 30 分钟。
4. 不要在高波动新闻时段第一次上线。
5. 第一天重点看系统行为,不要只看盈亏。

## 15. 紧急停机

systemd:

```bash
sudo systemctl stop trend-hl
```

Docker:

```bash
cd ~/trend-hl/docker
docker compose down
```

停机后立即在 Hyperliquid Web UI 检查:

1. 是否仍有 open orders。
2. 是否仍有持仓。
3. 是否需要手动平仓。
4. 是否怀疑 Agent 泄露并撤销 Agent。

程序停止不等于自动平仓。停止服务只是不再让机器人继续下新单;已有仓位和挂单必须在 Web UI 或专门脚本中确认。
