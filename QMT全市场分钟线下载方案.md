# QMT 全市场分钟线下载方案

## 结论

- 可以使用 Windows 上运行中的 `QMT + xtquant.xtdata` 下载 A 股全市场的历史 `1m` 数据。
- 不建议直接把 `2000-01-01` 到今天的全市场 1 分钟线一次性直接灌进 PostgreSQL 主表。
- 推荐链路：
  1. `QMT/xtdata` 下载历史分钟线
  2. 先落本地分区文件（优先 `Parquet`）
  3. 再按需批量导入 `PostgreSQL`

## 已落地文件

- 主脚本：
  - `/Users/wolf/Documents/DaiMa/TradingAgents-AShare-main/scripts/qmt_minute_history_sync.py`
- Windows 更新包：
  - `/Users/wolf/Documents/DaiMa/TradingAgents-AShare-main/windows_qmt_bridge_update/scripts/qmt_minute_history_sync.py`
  - `/Users/wolf/Documents/DaiMa/TradingAgents-AShare-main/windows_qmt_bridge_update/run_qmt_minute_history_sync.ps1`
  - `/Users/wolf/Documents/DaiMa/TradingAgents-AShare-main/windows_qmt_bridge_update/run_qmt_minute_history_sync.bat`

## 脚本能力

- 支持从 QMT 板块列表解析全市场股票池
- 支持 `2000-01-01` 到今天的历史窗口切分下载
- 优先输出本地 `Parquet` 分区文件
- 支持可选 `--import-db` 直接批量写入 `stock_minute_kline`
- 支持 `--import-existing-only`：只把已经下载好的分区文件批量导入 PostgreSQL
- 支持断点式复跑：
  - 已存在分区文件时默认跳过
  - 使用 `--force` 可覆盖重跑
- 会输出 `manifest.jsonl` 清单，记录每个股票、每个时间窗口的结果
- 支持失败重试：
  - `--retry-times`
  - `--retry-sleep`

## 与虚拟仓 Bridge 的关系

- 虚拟仓已经通过 `QMT Bridge` 连通 Windows QMT。
- 当前版本已复用这条 bridge，新增历史分钟线任务接口：
  - `POST /history/minute/sync`
  - `GET /history/minute/jobs/{job_id}`
- 回测数据里选择 `QMT` 后，后端固定调用 `QMT_HISTORY_ACCOUNT_KEY=paper_sim` 对应的模拟仓 Windows bridge，由 Windows 机器本地执行 `xtdata` 下载。
- 为避免误用实盘仓，后端不会自动回退到第一个可用 QMT 账户；如未找到模拟仓 bridge，任务会直接失败并提示配置问题。

关键要求：

- Windows QMT 机器必须更新 `windows_qmt_bridge_update/` 里的最新文件。
- 后端建议配置 `QMT_HISTORY_ACCOUNT_KEY=paper_sim`，并确保 `paper_sim` 的 `bridge_base_url` 指向 `http://192.168.10.1:8710`。
- `QMT_MINUTE_DATABASE_URL` 必须是 Windows 能访问的 PostgreSQL 地址。
- 如果数据库地址仍是 `postgresql://localhost/...`，Windows bridge 会访问自己的 localhost，无法写入 Mac 上的数据库。

## 推荐运行方式

### 方式一：先落分区文件（推荐）

在 Windows 上执行：

```powershell
cd D:\QMT
powershell -ExecutionPolicy Bypass -File .\run_qmt_minute_history_sync.ps1
```

默认输出目录：

```text
D:\QMT\data\minute_history
```

目录结构示例：

```text
period=1m/
  year=2000/
    symbol=600000.SH/
      600000.SH_20000101000000_20001231235959.parquet
```

### 方式二：下载后直接入 PostgreSQL

如果 Windows 机器能直接访问 PostgreSQL，可执行：

```powershell
python scripts\qmt_minute_history_sync.py `
  --sector all_a `
  --period 1m `
  --start-date 2000-01-01 `
  --end-date 2026-04-22 `
  --output-root D:\QMT\data\minute_history `
  --format parquet `
  --import-db `
  --database-url "postgresql://用户名:密码@IP:5432/数据库名"
```

### 方式三：只把已有 Parquet 导入 PostgreSQL

如果你已经先完整下载到了 `D:\QMT\data\minute_history`，后续只想导库，不想再次触发 xtdata 下载：

```powershell
$env:QMT_MINUTE_DATABASE_URL="postgresql://用户名:密码@IP:5432/数据库名"
cd D:\QMT
powershell -ExecutionPolicy Bypass -File .\run_qmt_minute_history_import.ps1
```

或直接调用脚本：

```powershell
python scripts\qmt_minute_history_sync.py `
  --sector all_a `
  --period 1m `
  --start-date 2000-01-01 `
  --end-date 2026-04-22 `
  --output-root D:\QMT\data\minute_history `
  --format parquet `
  --import-db `
  --import-existing-only `
  --database-url "postgresql://用户名:密码@IP:5432/数据库名"
```

## 参数说明

- `--sector`：股票池，默认 `all_a`
- `--symbols`：直接传股票代码列表
- `--symbols-file`：从文件读取股票列表
- `--start-date` / `--end-date`：日期区间
- `--window-days`：每次拉取的时间窗口天数，默认 `365`
- `--limit-symbols`：只下载前 N 只，便于试跑
- `--format`：`parquet` 或 `csv`
- `--import-db`：导出后直接同步写入 `PostgreSQL`
- `--import-existing-only`：只导入已有分区文件，不再次从 QMT 下载
- `--force`：覆盖已有分区文件
- `--retry-times`：单窗口失败后重试次数
- `--retry-sleep`：重试间隔秒数
- `--dry-run`：只解析股票池和任务窗口，不实际下载

## 推荐试跑顺序

不要直接上来就跑全市场 26 年全量，建议按下面顺序试跑：

1. 先试 10 只股票

```powershell
python scripts\qmt_minute_history_sync.py --sector all_a --limit-symbols 10 --start-date 2024-01-01 --end-date 2024-12-31 --dry-run
```

2. 再试真实下载 10 只股票

```powershell
python scripts\qmt_minute_history_sync.py --sector all_a --limit-symbols 10 --start-date 2024-01-01 --end-date 2024-12-31
```

3. 再试近 1 年全市场

4. 最后再跑多年历史补齐

5. 下载完成后，再单独执行一次 `import-existing-only` 导入 PostgreSQL

## 注意事项

- 最终是否能拿到 `2000 年以来` 的完整分钟线，取决于：
  - QMT 行情权限
  - 本地数据服务器可下载范围
  - xtdata 对历史分钟线的实际回补能力
- 建议先用 `--dry-run --limit-symbols 10` 确认你机器上的板块别名可用，再实际开跑
- 如果板块别名解析不到股票，可把 QMT 终端里真实板块名直接传给 `--sector`
- 数据量极大，建议优先保存为分区文件，不要直接长期只依赖 PostgreSQL 主表
- 若后续回测引擎主要读取分钟线，推荐仍以：
  - `Parquet + DuckDB/Polars`
  - PostgreSQL 仅保存元数据 / 下载进度 / 小摘要

## 下一步建议

- 第一阶段：先在 Windows 上验证 `近一年 + 100 只股票`
- 第二阶段：验证 `--import-db`
- 第三阶段：再做“全市场全历史补齐”
- 第四阶段：我再补一个“分钟线下载任务看板 + 断点重试 UI”
