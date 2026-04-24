# QMT 仓位模块接入说明

## 当前设计

- 项目已支持多 QMT 账户并行接入。
- 账户角色支持：
  - `paper`：模拟仓
  - `live`：实盘仓
- 前端入口：
  - `/virtual-warehouse`：虚拟仓（模拟盘）
  - `/live-warehouse`：实盘仓
  - `/tracking-board`：跟踪看板（独立仓位，不读取 QMT 仓位）
- 后端接口：
  - `GET /v1/virtual-warehouse/qmt/overview`
  - `GET /v1/virtual-warehouse/qmt/diagnostics`
  - `GET /v1/virtual-warehouse/qmt/orders`
  - `GET /v1/virtual-warehouse/qmt/trades`
  - `POST /v1/virtual-warehouse/qmt/orders`
  - `POST /v1/virtual-warehouse/qmt/orders/{order_id}/cancel`

## 三仓独立原则

- `跟踪看板`：继续保持你原来的独立仓位逻辑，不自动读取 QMT 模拟盘/实盘。
- `虚拟仓`：只映射 QMT 模拟盘，用于模拟测试、策略联调。
- `实盘仓`：只映射 QMT 实盘账户，用于核对真实资产、持仓、委托、成交。
- 当前版本已经关闭“QMT 自动同步到跟踪看板”的实际写入链路。
- 历史上如果数据库里存在 `qmt_virtual:*` 或 `qmt_live:*` 源数据，跟踪看板和分析上下文也会自动忽略。

## 推荐配置

在后端运行环境的 `.env` 中配置：

```env
QMT_DEFAULT_ACCOUNT_KEY=paper_sim
QMT_BRIDGE_BASE_URL=http://192.168.10.1:8710
QMT_BRIDGE_TOKEN=your-bridge-token
QMT_HISTORY_ACCOUNT_KEY=paper_sim
QMT_ACCOUNTS_JSON=[{"key":"paper_sim","enabled":true,"role":"paper","host":"192.168.10.1","port":58610,"account_id":"39027628","account_type":"STOCK","account_name":"国金QMT模拟仓","userdata_path":"D:/国金QMT交易端模拟/userdata_mini","bridge_base_url":"http://192.168.10.1:8710","bridge_token":"your-bridge-token","refresh_interval_seconds":10},{"key":"live_real","enabled":true,"role":"live","host":"192.168.10.1","port":58610,"account_id":"8886186680","account_type":"STOCK","account_name":"国金QMT实盘仓","userdata_path":"D:/国金证券QMT交易端/userdata_mini","bridge_base_url":"http://192.168.10.1:8711","bridge_token":"your-bridge-token","refresh_interval_seconds":10}]
```

## 双 QMT 如何运行

你这边的推荐方式是：**Windows 同时开两个 QMT 客户端 + 两个 bridge 进程 + 两个端口**。

- 模拟盘：
  - `userdata_mini`：`D:\国金QMT交易端模拟\userdata_mini`
  - 账号：`39027628`
  - bridge 端口：`8710`
- 实盘：
  - `userdata_mini`：`D:\国金证券QMT交易端\userdata_mini`
  - 账号：`8886186680`
  - bridge 端口：`8711`

## Windows 一键启动

项目已提供两套启动文件：

- 模拟盘：
  - `start_qmt_bridge.bat`
  - `start_qmt_bridge.ps1`
- 实盘：
  - `start_qmt_bridge_live.bat`
  - `start_qmt_bridge_live.ps1`

使用方式：

- 在 Windows 上先登录模拟 QMT，再双击 `start_qmt_bridge.bat`
- 再登录实盘 QMT，再双击 `start_qmt_bridge_live.bat`
- 两个 bridge 必须监听不同端口，不能共用

## Windows 文件替换步骤

Windows 侧也需要同步更新，否则后端三仓隔离已经生效，但 QMT Bridge 仍可能停留在旧版本。

把项目目录里的 `windows_qmt_bridge_update/` 整个复制到 Windows 的 `D:\QMT\`，覆盖同名文件。最终应包含：

- `D:\QMT\start_qmt_bridge.bat`
- `D:\QMT\start_qmt_bridge.ps1`
- `D:\QMT\start_qmt_bridge_live.bat`
- `D:\QMT\start_qmt_bridge_live.ps1`
- `D:\QMT\run_qmt_minute_history_sync.bat`
- `D:\QMT\run_qmt_minute_history_sync.ps1`
- `D:\QMT\run_qmt_minute_history_import.bat`
- `D:\QMT\run_qmt_minute_history_import.ps1`
- `D:\QMT\scripts\qmt_bridge_server.py`
- `D:\QMT\scripts\qmt_minute_history_sync.py`

更新后：

- 模拟盘 QMT 登录后，启动 `D:\QMT\start_qmt_bridge.bat`，监听 `8710`
- 实盘 QMT 登录后，启动 `D:\QMT\start_qmt_bridge_live.bat`，监听 `8711`
- 不要让模拟盘和实盘共用同一个 bridge 端口
- 模拟盘 bridge 默认 `QMT_BRIDGE_ROLE=paper` 且允许交易联调
- 实盘 bridge 默认 `QMT_BRIDGE_ROLE=live` 且 `QMT_BRIDGE_ALLOW_TRADING=0`，只读锁定

## 接入要求

- 后端必须运行在安装了 `xtquant` 的 Windows 环境。
- 每个 QMT 账户建议使用独立的 `userdata_mini` 目录。
- 不建议多个连接共用同一个 `userdata_mini`。
- `192.168.10.1:58610` 更偏行情/通信入口，真实资产与持仓读取仍依赖 `xttrader + StockAccount + userdata_mini`。
- 如果主服务不在 Windows 上，推荐在 Windows QMT 机器上启动桥接服务：`/Users/wolf/Documents/DaiMa/TradingAgents-AShare-main/scripts/qmt_bridge_server.py`

桥接接口：

- `GET /health`
- `GET /snapshot?account_id=39027628&account_type=STOCK&account_key=paper_sim`
- `POST /orders`
- `POST /orders/{order_id}/cancel`

安全规则：

- 后端 QMT 交易接口只允许 `role=paper` 的账户提交委托和撤单。
- `role=live` 的实盘仓只允许查询资产、持仓、委托和成交；下单/撤单会被后端与 bridge 双重拒绝。
- QMT 审计日志会记录 `account_key/account_id/role/bridge_url/action/request_id`，可在实时日志页排查通道调用。

## 当前页面能力

- 展示账户总资产、总盈亏、当日盈亏、总市值、可用资金。
- 展示持仓明细：股票名称/代码、盈亏金额/比例、持仓/可用、成本/现价、持股天数、回本涨幅、市值占比。
- 虚拟仓支持 QMT 下单、撤单、查看最近委托、最近成交。
- 实盘仓只读展示资产、持仓、委托和成交，不提供下单/撤单入口。
- 支持连接诊断，检查：
  - 是否启用
  - 账号是否配置
  - `userdata_mini` 是否配置且存在
  - `xtquant` 是否已安装
  - 是否可真实连接
- 模拟仓支持从页面直接把策略运行到纸交易账户
- 实盘仓与跟踪看板逻辑隔离，页面只负责映射 QMT 实盘状态

## 正式运营建议

- 第一阶段：`模拟仓 + 实盘仓 + 跟踪看板` 三者并行、各自独立。
- 第二阶段：如需更多账户，优先按“每账户独立目录、独立实例”扩展。
- 生产环境建议额外补：
  - 账户级连接超时与重试
  - 断线告警（当前已支持企业微信基础版）
  - 实盘与模拟仓权限隔离

## 全市场分钟线下载

如果你要从 Windows 上的 QMT 下载全市场历史 `1m` 数据，项目已经补了专用脚本：

- 方案文档：`/Users/wolf/Documents/DaiMa/TradingAgents-AShare-main/QMT全市场分钟线下载方案.md:1`
- Windows 运行脚本：
  - `D:\QMT\run_qmt_minute_history_sync.ps1`
  - `D:\QMT\run_qmt_minute_history_import.ps1`

推荐流程：

1. 在 Windows QMT 机器上先下载到本地分区文件
2. 确认数据完整后，再单独导入 PostgreSQL
3. 回测优先直接读取 `Parquet + DuckDB/Polars`，数据库只作为统一数据源和补充查询

### 复用虚拟仓 Bridge 下载分钟线

当前版本已支持 Mac 后端复用虚拟仓的 QMT Bridge 连接发起历史分钟线下载：

- Bridge 新增 `POST /history/minute/sync`
- Bridge 新增 `GET /history/minute/jobs/{job_id}`
- 回测数据页面选择 `QMT + 股票1分钟K线` 后，后端固定使用 `QMT_HISTORY_ACCOUNT_KEY=paper_sim` 对应的模拟仓 Bridge，不会回退到实盘 Bridge

注意：

- 必须把 `windows_qmt_bridge_update/` 复制到 Windows 的 `D:\QMT\` 并重启 bridge。
- 必须配置 `QMT_MINUTE_DATABASE_URL` 为 Windows 能访问的 PostgreSQL 地址，不能使用 `localhost`。
- 如需联调虚拟仓全流程，可先运行只读脚本：`python scripts/qmt_paper_flow_check.py`；确认安全后再追加 `--submit-cancel-test` 做模拟委托/撤单验证。
